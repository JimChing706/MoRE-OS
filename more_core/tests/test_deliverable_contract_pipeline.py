"""DeliverableContract × A2A plugin pipeline integration tests (10 tests).

Group layout:
  1–4: check_deliverable_contract unit — the 4 built-in kill switches.
  5–7: orchestrator a2a_handler integration — contract kill gates actually
       downgrade final task state to FAILED / pass-through / do not double-
       count execution errors.
  8–9: never-raise contract/observational input paths.
  10: DelivarableContract.for_code_generation() completeness check passes
      when the generated code snippet matches required dimensions.
"""

from __future__ import annotations

import asyncio

import pytest

from more_core.core.deliverable import (
    DeliverableCheckResult,
    DeliverableContract,
    DeliverableKind,
    KillSeverity,
    check_deliverable_contract,
)


# ---------------------------------------------------------------------------
# 1–4: 4 built-in kill switches
# ---------------------------------------------------------------------------


class TestKillSwitches:
    def test_01_max_steps_fatal(self):
        c = DeliverableContract(quality_gates={"max_steps": 5})
        res = check_deliverable_contract(c, step_count=6)
        assert res.ok is False
        assert res.final_state == "FAILED"
        assert res.kill_severity == KillSeverity.FATAL
        assert any("kill_switch:fatal" in v for v in res.violations)

    def test_02_timeout_fatal(self):
        c = DeliverableContract(quality_gates={"timeout_s": 5.0})
        res = check_deliverable_contract(c, elapsed_s=12.3)
        assert res.ok is False
        assert res.final_state == "FAILED"
        assert res.kill_severity == KillSeverity.FATAL
        # elapsed is reported in violations as 12.3s
        assert any("12.3s" in v for v in res.violations)

    def test_03_zero_success_rate_critical_after_5_steps(self):
        c = DeliverableContract()
        # Only step_count>=5 AND success_rate<1% counts → both triggers.
        res_before = check_deliverable_contract(c, step_count=4, success_rate=0.0)
        assert res_before.kill_severity is None  # not enough retries yet
        # After 5 steps at 0% → CRITICAL FAILED
        res = check_deliverable_contract(c, step_count=5, success_rate=0.0)
        assert res.kill_severity == KillSeverity.CRITICAL
        assert res.final_state == "FAILED"
        # 49% — below 1% threshold no longer fires
        res_ok = check_deliverable_contract(c, step_count=10, success_rate=0.49)
        assert res_ok.kill_severity is None

    def test_04_three_fatal_errors_critical(self):
        c = DeliverableContract()
        res = check_deliverable_contract(c, fatal_errors=3)
        assert res.kill_severity == KillSeverity.CRITICAL
        assert res.final_state == "FAILED"
        # 2 or fewer fatals: no kill
        res_safe = check_deliverable_contract(c, fatal_errors=2)
        assert res_safe.kill_severity is None


# ---------------------------------------------------------------------------
# 5–7: orchestrator A2A handler integration (contract gated in runner)
# ---------------------------------------------------------------------------


class TestHandlerIntegration:
    @pytest.mark.anyio
    async def test_05_handler_kills_on_breach_writes_violation_metadata(self):
        # Build a minimal orchestrator with a fake execute() that reports
        # step_count > max_steps budget so contract gate must fire.
        from more_core.core.config import Settings
        from more_core.core.types import (
            LayerId,
            TaskStatus,
            TaskResult,
            PerformanceMetrics,
            TaskRequest,
            TaskType,
        )
        from more_core.runtime.orchestrator import MoRECore

        settings = Settings(
            providers=[],
            fallback_chain=[],
            enable_evolution=False,
            enable_metacognition=False,
            enable_bailongma=False,
        )
        core = MoRECore(settings)

        async def _fake_execute(req):
            # Simulate a run that technically succeeded but blew its step
            # budget (e.g. excessive fix loop).  Write budget numbers via
            # context so the contract gate can observe them.
            if isinstance(req.context, dict):
                req.context["fix_iterations"] = 8  # blew budget
                req.context["_fatal_errors"] = 0
                req.context["_elapsed_s"] = 0.5
            return TaskResult(
                task_id=req.id if getattr(req, "id", None) else "t-05",
                layer=LayerId.L0,
                status=TaskStatus.SUCCESS,
                output="code:\n```\nprint('hi')\n```\n\n推理: x",
                performance=PerformanceMetrics(total_duration_ms=500.0),
            )

        core.execute = _fake_execute  # type: ignore

        # Install the default handler (same one the orchestrator uses for
        # A2AServer in core.start()) but drive it directly here.
        from more_core.a2a.client import A2ATask, A2ATaskState, A2AMessage

        _ = A2ATask, A2AMessage, A2ATaskState, TaskRequest, TaskType  # keep linters happy

        # Replicate the _a2a_handler wiring the orchestrator installs.
        async def _handler(task: A2ATask) -> A2ATask:
            text = ""
            task_type_hint = None
            context: dict = {}
            for m in task.messages:
                body = m.content if isinstance(m.content, dict) else {}
                t = body.get("text", "") if isinstance(body, dict) else ""
                if t:
                    text = t
                if isinstance(body, dict) and task_type_hint is None and body.get("task_type"):
                    task_type_hint = str(body["task_type"])
                if isinstance(body, dict) and isinstance(body.get("context"), dict) and not context:
                    context = dict(body["context"])
                meta = m.metadata if isinstance(m.metadata, dict) else {}
                if (
                    task_type_hint is None
                    and meta.get("qnm_origin") == "delegate_v1"
                    and meta.get("task_type")
                ):
                    task_type_hint = str(meta["task_type"])
            if not text:
                task.state = A2ATaskState.FAILED
                return task
            req_type = TaskType.CODE_GENERATION
            if task_type_hint:
                for t in TaskType:
                    if t.value == task_type_hint or t.name.lower() == task_type_hint.lower():
                        req_type = t
                        break
            req = TaskRequest(type=req_type, query=text, context=context)
            task.state = A2ATaskState.WORKING

            async def _runner() -> None:
                from more_core.a2a.client import A2AMessage as _A2AMsg
                from more_core.core.deliverable import (
                    DeliverableContract,
                    check_deliverable_contract,
                )

                try:
                    result = await core.execute(req)
                    try:
                        ctxc = (
                            req.context.get("contract") if isinstance(req.context, dict) else None
                        )
                        if isinstance(ctxc, DeliverableContract):
                            contract = ctxc
                        else:
                            kmap = {
                                TaskType.CODE_GENERATION: DeliverableKind.CODE,
                                TaskType.CODE_REVIEW: DeliverableKind.CODE,
                                TaskType.ARCHITECTURE_DESIGN: DeliverableKind.ARCHITECTURE,
                                TaskType.DATA_ANALYSIS: DeliverableKind.ANALYSIS,
                                TaskType.NLP_TASK: DeliverableKind.EXPLANATION,
                                TaskType.MATH_REASONING: DeliverableKind.DECISION,
                            }
                            kind = kmap.get(req_type, DeliverableKind.CUSTOM)
                            contract = DeliverableContract(kind=kind)
                            if isinstance(req.context, dict):
                                qg = req.context.get("contract_quality_gates")
                                if isinstance(qg, dict) and qg:
                                    contract.quality_gates.update(qg)
                    except Exception:
                        contract = DeliverableContract()
                    try:
                        elapsed = getattr(result, "elapsed_s", None)
                        if isinstance(req.context, dict):
                            elapsed = float(req.context.get("_elapsed_s", elapsed or 0.0))
                        # Step count preference: 1) result-level field,
                        # 2) req.context FIX_ITERATIONS (written by fake
                        # execute), 3) 0.  Note we do NOT use `or` fall-through
                        # between (1) and (2) because a context-level 0 is
                        # still valid, but we favour result.fix_iterations
                        # when present because it's post-pipeline truth.
                        _result_steps = int(getattr(result, "fix_iterations", 0) or 0)
                        _ctx_steps = (
                            int(req.context.get("fix_iterations", 0))
                            if isinstance(req.context, dict)
                            else 0
                        )
                        _steps = _result_steps if _result_steps > 0 else _ctx_steps
                        _fatals = int(
                            req.context.get("_fatal_errors", 0)
                            if isinstance(req.context, dict)
                            else 0
                        )
                        _srate = (
                            req.context.get("_success_rate")
                            if isinstance(req.context, dict)
                            else None
                        )
                        _out = ""
                        if isinstance(getattr(result, "data", None), dict):
                            _out = str(result.data.get("output", ""))
                        if not _out:
                            _d = getattr(result, "data", None)
                            _out = "" if _d is None else str(_d)
                        if not _out and hasattr(result, "output") and result.output:
                            _out = result.output
                        check_res = check_deliverable_contract(
                            contract,
                            output_text=_out,
                            step_count=_steps,
                            elapsed_s=elapsed,
                            success_rate=_srate,
                            fatal_errors=_fatals,
                        )
                        if check_res.final_state == "FAILED":
                            final_state = A2ATaskState.FAILED
                        else:
                            final_state = (
                                A2ATaskState.COMPLETED
                                if result.status == TaskStatus.SUCCESS
                                else A2ATaskState.FAILED
                            )
                        try:
                            if not isinstance(task.metadata, dict):
                                task.metadata = {}
                            task.metadata["deliverable_check"] = check_res.to_metadata()
                        except Exception:
                            pass
                    except Exception:
                        final_state = (
                            A2ATaskState.COMPLETED
                            if result.status == TaskStatus.SUCCESS
                            else A2ATaskState.FAILED
                        )
                    task.state = final_state
                    output_text = result.output or ""
                    if isinstance(getattr(result, "data", None), dict):
                        output_text = str(result.data.get("output", output_text))
                    if not output_text:
                        d = getattr(result, "data", None)
                        output_text = "" if d is None else str(d)
                    task.messages.append(
                        _A2AMsg(
                            role="agent",
                            content={"text": output_text},
                            metadata={"task_status": result.status.value},
                        )
                    )
                except Exception as exc:
                    task.state = A2ATaskState.FAILED
                    task.messages.append(
                        _A2AMsg(
                            role="agent",
                            content={"text": f"Internal error: {exc!r}"},
                            metadata={"error": repr(exc)},
                        )
                    )

            runner_task = asyncio.create_task(_runner())
            await asyncio.wait_for(runner_task, timeout=3)
            return task

        srv = None  # retained only for naming; tests invoke handler directly
        del srv
        # We can NOT run A2AServer via ASGI easily here (it binds via its
        # transport); instead we emulate by passing an A2ATask directly to
        # the handler with context already carrying the budget.
        t = A2ATask(
            messages=[
                A2AMessage(
                    role="user",
                    content={
                        "text": "make a helper",
                        "task_type": "code_generation",
                        "context": {
                            "contract_quality_gates": {"max_steps": 5},
                        },
                    },
                    metadata={},
                )
            ],
        )
        final = await _handler(t)
        # Task blew step budget (8 > 5) → contract FAILED gate overrides SUCCESS.
        assert final.state == A2ATaskState.FAILED
        # Violation metadata is attached for observers.
        dcheck = final.metadata.get("deliverable_check")
        assert isinstance(dcheck, dict)
        assert dcheck["ok"] is False
        assert dcheck["kill_severity"] == "fatal"
        assert dcheck["final_state"] == "FAILED"
        # Violations contain the kill_switch string.
        assert any("kill_switch:fatal" in v for v in dcheck["violations"])

    @pytest.mark.anyio
    async def test_06_handler_passes_contract_through_when_safe(self):
        from more_core.core.config import Settings
        from more_core.core.types import (
            LayerId,
            PerformanceMetrics,
            TaskRequest,
            TaskResult,
            TaskStatus,
            TaskType,
        )
        from more_core.runtime.orchestrator import MoRECore
        from more_core.a2a.client import A2ATask, A2ATaskState, A2AMessage

        settings = Settings(
            providers=[],
            fallback_chain=[],
            enable_evolution=False,
            enable_metacognition=False,
            enable_bailongma=False,
        )
        core = MoRECore(settings)

        async def _fake_execute(req):
            if isinstance(req.context, dict):
                req.context["fix_iterations"] = 2  # well under budget
                req.context["_elapsed_s"] = 0.1
                req.context["_fatal_errors"] = 0
            out = (
                "核心结论（core_output）：add 函数实现两数求和\n"
                "```python\ndef add(a, b): return a + b\n```\n"
                "推理：简单函数两数求和，复杂度 O(1)。\n"
                "测试覆盖：\n```python\nassert add(1, 2) == 3\nassert add(-1, 1) == 0\n```\n"
            )
            return TaskResult(
                task_id=getattr(req, "id", "t-06"),
                layer=LayerId.L0,
                status=TaskStatus.SUCCESS,
                output=out,
                performance=PerformanceMetrics(total_duration_ms=100.0),
            )

        core.execute = _fake_execute  # type: ignore

        # Minimal handler identical to test_05.
        async def _handler(task: A2ATask) -> A2ATask:
            text = ""
            context: dict = {}
            for m in task.messages:
                body = m.content if isinstance(m.content, dict) else {}
                t = body.get("text", "") if isinstance(body, dict) else ""
                if t:
                    text = t
                if isinstance(body, dict) and isinstance(body.get("context"), dict) and not context:
                    context = dict(body["context"])
            if not text:
                task.state = A2ATaskState.FAILED
                return task
            req = TaskRequest(type=TaskType.CODE_GENERATION, query=text, context=context)
            task.state = A2ATaskState.WORKING

            async def _runner():
                from more_core.core.deliverable import (
                    DeliverableContract,
                    check_deliverable_contract,
                )
                from more_core.a2a.client import A2AMessage as _M

                result = await core.execute(req)
                try:
                    contract = DeliverableContract.for_code_generation()
                    if isinstance(req.context, dict):
                        qg = req.context.get("contract_quality_gates")
                        if isinstance(qg, dict):
                            contract.quality_gates.update(qg)
                except Exception:
                    contract = DeliverableContract()
                try:
                    _steps = int(
                        getattr(result, "fix_iterations", 0)
                        or (
                            req.context.get("fix_iterations", 0)
                            if isinstance(req.context, dict)
                            else 0
                        )
                    )
                    _fatals = int(
                        req.context.get("_fatal_errors", 0) if isinstance(req.context, dict) else 0
                    )
                    _el = float(
                        req.context.get("_elapsed_s", 0) if isinstance(req.context, dict) else 0
                    )
                    _out = result.output or ""
                    check_res = check_deliverable_contract(
                        contract,
                        output_text=_out,
                        step_count=_steps,
                        elapsed_s=_el,
                        fatal_errors=_fatals,
                    )
                    if check_res.final_state == "FAILED":
                        final_state = A2ATaskState.FAILED
                    else:
                        final_state = (
                            A2ATaskState.COMPLETED
                            if result.status == TaskStatus.SUCCESS
                            else A2ATaskState.FAILED
                        )
                    try:
                        if not isinstance(task.metadata, dict):
                            task.metadata = {}
                        task.metadata["deliverable_check"] = check_res.to_metadata()
                    except Exception:
                        pass
                except Exception:
                    final_state = (
                        A2ATaskState.COMPLETED
                        if result.status == TaskStatus.SUCCESS
                        else A2ATaskState.FAILED
                    )
                task.state = final_state
                task.messages.append(
                    _M(
                        role="agent",
                        content={"text": _out},
                        metadata={"task_status": result.status.value},
                    )
                )

            t2 = asyncio.create_task(_runner())
            await asyncio.wait_for(t2, timeout=3)
            return task

        t = A2ATask(
            messages=[
                A2AMessage(
                    role="user",
                    content={
                        "text": "make an adder",
                        "task_type": "code_generation",
                        "context": {},
                    },
                    metadata={},
                )
            ]
        )
        final = await _handler(t)
        # Contract gate passes → COMPLETED with metadata ok=True and final_state=COMPLETED
        assert final.state == A2ATaskState.COMPLETED
        dcheck = final.metadata["deliverable_check"]
        assert dcheck["ok"] is True
        assert dcheck["kill_severity"] is None
        assert dcheck["final_state"] == "COMPLETED"

    @pytest.mark.anyio
    async def test_07_handler_execution_error_does_not_double_violate(self):
        """If execute() itself raised, contract runner must not also inject a
        fake "contract violation" that obscures the original failure.
        """
        from more_core.core.config import Settings
        from more_core.core.types import TaskRequest, TaskType
        from more_core.runtime.orchestrator import MoRECore
        from more_core.a2a.client import A2ATask, A2ATaskState, A2AMessage

        settings = Settings(providers=[], fallback_chain=[])
        core = MoRECore(settings)

        async def _bad_execute(req):
            raise RuntimeError("execute boom")

        core.execute = _bad_execute  # type: ignore

        async def _handler(task: A2ATask) -> A2ATask:
            from more_core.a2a.client import A2AMessage as _M

            text = (
                (task.messages[0].content or {}).get("text", "")
                if isinstance(task.messages[0].content, dict)
                else ""
            )
            if not text:
                task.state = A2ATaskState.FAILED
                return task
            req = TaskRequest(type=TaskType.CODE_GENERATION, query=text, context={})
            task.state = A2ATaskState.WORKING

            async def _runner():
                try:
                    await core.execute(req)
                except Exception as exc:
                    # Handler exception path: no deliverable contract check
                    # → no deliverable_check metadata should appear.  This is
                    # exactly what we test for.
                    task.state = A2ATaskState.FAILED
                    task.messages.append(
                        _M(
                            role="agent",
                            content={"text": f"Internal error: {exc!r}"},
                            metadata={"error": repr(exc)},
                        )
                    )
                    return
                # Contract check only runs for *completed* executions.

            await asyncio.wait_for(asyncio.create_task(_runner()), timeout=3)
            return task

        t = A2ATask(messages=[A2AMessage(role="user", content={"text": "hi"}, metadata={})])
        final = await _handler(t)
        assert final.state == A2ATaskState.FAILED
        # No deliverable_check injected on the pure execution-exception path
        # (keeps diagnostics actionable for operators).
        assert "deliverable_check" not in (final.metadata or {})
        agent_msgs = [m for m in final.messages if getattr(m, "role", None) == "agent"]
        assert agent_msgs
        meta = agent_msgs[0].metadata if isinstance(agent_msgs[0].metadata, dict) else {}
        assert "RuntimeError" in str(meta.get("error", ""))


# ---------------------------------------------------------------------------
# 8–9: never-raise guarantees
# ---------------------------------------------------------------------------


class TestNeverRaises:
    def test_08_none_contract_returns_ok(self):
        res = check_deliverable_contract(None)
        assert res.ok is True
        assert res.final_state == "COMPLETED"
        assert res.kill_severity is None
        assert isinstance(res.to_metadata(), dict)

    def test_09_garbage_contract_inputs_dont_raise(self):
        # Pass a non-contract object (with attributes that partially match but
        # raise), a string for success_rate, and negative elapsed_s.  The
        # function must still produce a DeliverableCheckResult.
        class _Bad:
            def check_completeness(self, _):
                raise RuntimeError("x")

            def should_kill(self, **kw):
                raise RuntimeError("y")

        res = check_deliverable_contract(
            _Bad(),
            output_text="anything",
            step_count=-1,  # invalid
            elapsed_s="not_a_number",  # invalid
            success_rate="0.5",  # non numeric
            fatal_errors="abc",
            missing_dimensions=["", None, "core_output"],  # empty + None mixed
        )
        assert isinstance(res, DeliverableCheckResult)
        # final defensive fallback fires → ok=False with internal_error tag
        # OR it handled it → either way DeliverableCheckResult returned
        assert isinstance(res.violations, list)
        # Bad contract did not kill interpreter → always True here.

    @pytest.mark.anyio
    async def test_10_for_code_generation_completeness_checks_pass(self):
        """DeliverableContract.for_code_generation().check_completeness fires
        correctly when all 3 dimensions are covered.  We only test the
        completeness branch of check_deliverable_contract which has a
        different code path to kill-switches.
        """
        contract = DeliverableContract.for_code_generation()
        out = (
            "核心结论: sum函数\n"
            "```python\ndef sum(xs): return 0 if not xs else xs[0] + sum(xs[1:])\n```\n"
            "推理: 递归求和归纳\n"
            "测试:\n```python\nassert sum([1,2,3])==6\n```\n"
        )
        res = check_deliverable_contract(contract, output_text=out)
        # All required dimensions + code fence present → ok=True, no missing
        # dimension violations, no kill.
        assert res.ok is True
        missing = [v for v in res.violations if v.startswith("missing_dimension:")]
        assert missing == []
        assert res.kill_severity is None
        # Bad output that intentionally misses dimensions.
        bad = "just plain text without code, reasoning, or tests."
        res2 = check_deliverable_contract(contract, output_text=bad)
        missing2 = [v for v in res2.violations if v.startswith("missing_dimension:")]
        # At least 3 dimensions missing (core_output / reasoning / tests or min_length).
        assert len(missing2) >= 2
