"""Step-4 P0 独立测试集：A2A Bridge + 观测埋点 + Kill/Rollback + Feature 登记册.

Tests focus on behaviour, not network I/O.  Any real HTTP call is routed
through a temporary httpx ASGI/WSGI TestClient-like in-process server or
mocked; no network access is required for these tests to pass on a CI box
with localhost-only connectivity.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

pytest_plugins: list[str] = []  # placeholder — mark only async tests with @pytest.mark.asyncio


# ---------------------------------------------------------------------------
# P0-A: BaiLongma A2A Bridge v1 — ping / echo / delegate / cancel
# ---------------------------------------------------------------------------


class TestBaiLongmaBridge:
    @staticmethod
    def _bridge(monkeypatch, endpoint: str = "http://in-memory/rpc"):
        from more_core.a2a.bailongma_bridge import BaiLongmaBridge

        return BaiLongmaBridge(endpoint=endpoint)

    def test_disabled_by_default_no_endpoint(self):
        from more_core.a2a.bailongma_bridge import BaiLongmaBridge

        b = BaiLongmaBridge(endpoint="")
        assert b.enabled is False

    @pytest.mark.asyncio
    async def test_ping_no_endpoint_returns_disconnected(self):
        from more_core.a2a.bailongma_bridge import BaiLongmaBridge

        b = BaiLongmaBridge(endpoint="")
        status = await b.ping()
        assert status.reachable is False
        assert "not configured" in status.error

    @pytest.mark.asyncio
    async def test_echo_disabled_returns_empty_string(self):
        from more_core.a2a.bailongma_bridge import BaiLongmaBridge

        b = BaiLongmaBridge(endpoint="")
        assert await b.echo("hi") == ""

    @pytest.mark.asyncio
    async def test_delegate_disabled_returns_none(self):
        from more_core.a2a.bailongma_bridge import BaiLongmaBridge

        b = BaiLongmaBridge(endpoint="")
        assert await b.delegate_task(task_type="code_generation", query="hi") is None

    @pytest.mark.asyncio
    async def test_cancel_disabled_returns_false(self):
        from more_core.a2a.bailongma_bridge import BaiLongmaBridge

        b = BaiLongmaBridge(endpoint="")
        assert await b.cancel_task("any") is False

    @pytest.mark.asyncio
    async def test_ping_bad_endpoint_returns_status_with_error(self):
        """Endpoint that 404s or refuses is *not* an exception — it's a BridgeStatus."""
        from more_core.a2a.bailongma_bridge import BaiLongmaBridge

        b = BaiLongmaBridge(endpoint="http://127.0.0.1:1/definitely-not-listening")
        status = await b.ping()
        # Should have reachable=False; no exceptions leaked out.
        assert status.reachable is False
        assert status.error != ""


# ---------------------------------------------------------------------------
# P0-B: observability — llm_calls + injection_hits tables
# ---------------------------------------------------------------------------


class TestObservabilityTables:
    @pytest.fixture(autouse=True)
    def _fresh_db(self, tmp_path: Path, monkeypatch):
        from more_core.governance import observability as obs

        obs.close()
        monkeypatch.setenv("MORE_PROJECT_ROOT", str(tmp_path))
        # Module singleton is stateful; reset via module-level configure().
        obs.configure(tmp_path / "t_obs.sqlite")
        yield
        obs.close()

    def test_record_and_query_llm_call(self):
        from more_core.governance import observability as obs

        obs.record_llm_call(
            request_id="r-1",
            provider="ollama",
            model="qwen2.5:7b",
            prompt_chars=100,
            prompt_tokens=33,
            completion_tokens=11,
            latency_ms=120.5,
            success=True,
        )
        rows = obs.query_recent_llm(10)
        assert len(rows) == 1
        assert rows[0]["provider"] == "ollama"
        assert rows[0]["success"] == 1
        assert rows[0]["latency_ms"] == pytest.approx(120.5, abs=0.01)

    def test_record_llm_unique_rid_attempt(self):
        """UNIQUE(request_id, attempt) keeps rows separate across retries."""
        from more_core.governance import observability as obs

        for i in range(3):
            obs.record_llm_call(
                request_id="r-same",
                provider="ollama",
                model="m",
                prompt_chars=1,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0.0,
                success=False,
                error="boom",
                attempt=i,
            )
        rows = obs.query_recent_llm(10)
        assert len(rows) == 3

    def test_record_injection_and_stats(self):
        from more_core.governance import observability as obs

        for origin in ("evolution_bias", "dynamic_k", "evolution_bias"):
            obs.record_injection(
                origin=origin,
                injection_site="l0_build_fix_prompt",
                key="fp-1",
                value_text="injected directive",
                applied=True,
                request_id="req-x",
            )
        stats = obs.query_injection_stats(3600)
        assert stats.get("evolution_bias") == 2
        assert stats.get("dynamic_k") == 1

    def test_write_is_defensive_no_exceptions(self, tmp_path: Path):
        """Even with a closed connection and a path you can't write to, no raise."""
        from more_core.governance import observability as obs

        obs.configure(tmp_path / "closed.sqlite")
        obs.close()
        # After close, configure was torn down; record shouldn't error.
        obs.record_llm_call(
            request_id="x", provider="a", model="b",
            prompt_chars=0, prompt_tokens=0, completion_tokens=0,
            latency_ms=0.0, success=True,
        )
        obs.record_injection(origin="o", injection_site="i", value_text="v")
        # Just need no exception.


# ---------------------------------------------------------------------------
# P0-C: kill switch + rollback
# ---------------------------------------------------------------------------


class TestDeliverableContractKillCriteria:
    def test_to_dict_round_trips_new_fields(self):
        from more_core.core.deliverable import DeliverableContract, KillCriterion, KillSeverity

        c = DeliverableContract(
            rollback_id="rb-1",
            kill_criteria=[
                KillCriterion(condition="timeout", severity=KillSeverity.FATAL, trigger="elapsed>10")
            ],
        )
        d = c.to_dict()
        assert d["rollback_id"] == "rb-1"
        assert len(d["kill_criteria"]) == 1
        assert d["kill_criteria"][0]["severity"] == "fatal"

    def test_builtin_max_steps_fatal(self):
        from more_core.core.deliverable import DeliverableContract, KillSeverity

        c = DeliverableContract(quality_gates={"max_steps": 3})
        assert c.should_kill(step_count=0) is None
        assert c.should_kill(step_count=4) == KillSeverity.FATAL

    def test_builtin_timeout_fatal(self):
        from more_core.core.deliverable import DeliverableContract, KillSeverity

        c = DeliverableContract(quality_gates={"timeout_s": 1.0})
        assert c.should_kill(elapsed_s=0.5) is None
        assert c.should_kill(elapsed_s=2.0) == KillSeverity.FATAL

    def test_low_success_rate_many_retries_critical(self):
        from more_core.core.deliverable import DeliverableContract, KillSeverity

        c = DeliverableContract()
        # step_count >=5 AND rate < 1%
        assert c.should_kill(step_count=4, success_rate=0.0) is None
        assert c.should_kill(step_count=6, success_rate=0.0) == KillSeverity.CRITICAL

    def test_many_fatal_errors_critical(self):
        from more_core.core.deliverable import DeliverableContract, KillSeverity

        c = DeliverableContract()
        assert c.should_kill(fatal_errors=2) is None
        assert c.should_kill(fatal_errors=3) == KillSeverity.CRITICAL


class TestTaskManagerKillSwitch:
    @pytest.fixture(autouse=True)
    def _reset_global(self):
        from more_core.cron.manager import set_global_killswitch, get_global_killswitch

        prev = get_global_killswitch()
        set_global_killswitch(False)
        yield
        set_global_killswitch(prev)

    def test_global_killswitch_toggle(self):
        from more_core.cron.manager import set_global_killswitch, get_global_killswitch

        assert get_global_killswitch() is False
        set_global_killswitch(True)
        assert get_global_killswitch() is True
        set_global_killswitch(False)
        assert get_global_killswitch() is False

    @pytest.mark.asyncio
    async def test_run_task_blocked_by_global_killswitch(self):
        from more_core.cron.manager import TaskManager, set_global_killswitch

        tm = TaskManager()
        seen = []

        async def _noop():
            seen.append(1)
            return "ok"

        tm.add_cron_task("job-1", "No-op", "* * * * *", _noop)
        # First run passes (no global KS).  run_task returns JobResult for
        # cron tasks (the scheduler's wrapper), so don't assert on exact
        # truthiness, just that the side effect happened.
        set_global_killswitch(True)
        res = await tm.run_task("job-1")
        assert res is None
        assert seen == []
        set_global_killswitch(False)
        # Revive: scheduler fires.  CronScheduler.run_job returns a
        # JobResult when the job is defined.
        await tm.run_task("job-1")
        assert seen == [1]

    @pytest.mark.asyncio
    async def test_per_task_kill_and_revive(self):
        from more_core.cron.manager import TaskManager

        tm = TaskManager()

        async def _fn():
            return 42

        tm.add_cron_task("j1", "t", "* * * * *", _fn)
        assert tm.kill_task("j1") is True
        assert tm.kill_task("missing") is False
        # Killed: run_task returns None.
        assert await tm.run_task("j1") is None
        # Revive: returns JobResult (truthy).
        assert tm.revive_task("j1") is True
        res = await tm.run_task("j1")
        assert res is not None

    @pytest.mark.asyncio
    async def test_rollback_stack_runs_lifo(self):
        from more_core.cron.manager import TaskManager

        tm = TaskManager()
        order: list[str] = []

        def mk(name: str):
            def _sync():
                order.append(name)

            return _sync

        tm.add_rollback("t1", name="first", rollback_fn=mk("first"))
        tm.add_rollback("t1", name="second", rollback_fn=mk("second"))
        result = await tm.rollback_task("t1")
        # Result list order == execution order (LIFO), i.e. [second, first]
        names = [r[0] for r in result]
        assert names == ["second", "first"]
        assert all(succeeded for _, succeeded, _ in result)
        # Calling rollback twice: stack was popped — empty second time.
        again = await tm.rollback_task("t1")
        assert again == []

    @pytest.mark.asyncio
    async def test_rollback_catches_individual_exceptions(self):
        from more_core.cron.manager import TaskManager

        tm = TaskManager()

        def good():
            return None

        def bad():
            raise RuntimeError("boom")

        tm.add_rollback("t", name="good", rollback_fn=good)
        tm.add_rollback("t", name="bad", rollback_fn=bad)
        result = await tm.rollback_task("t")
        # LIFO: bad runs first and fails, then good succeeds.
        names = [r[0] for r in result]
        assert names == ["bad", "good"]
        success = {r[0]: r[1] for r in result}
        assert success["bad"] is False
        assert success["good"] is True
        # The bad function's error message is captured in the tuple.
        err_map = {r[0]: r[2] for r in result}
        assert "boom" in err_map["bad"]

    def test_get_killswitch_state_structured(self):
        from more_core.cron.manager import TaskManager, set_global_killswitch

        set_global_killswitch(False)
        tm = TaskManager()

        async def _fn():
            return 0

        tm.add_cron_task("a", "", "* * * * *", _fn)
        tm.add_cron_task("b", "", "* * * * *", _fn)
        tm.kill_task("a")
        state = tm.get_killswitch_state()
        assert state["global_killed"] is False
        assert state["task_count_killed"] == 1
        assert state["killed_task_ids"] == ["a"]


# ---------------------------------------------------------------------------
# P0-D: feature flag register + Settings fusion defaults
# ---------------------------------------------------------------------------


class TestFeatureRegister:
    def test_register_has_expected_keys(self):
        from more_core.core.config import Settings

        reg = Settings.feature_register()
        for required in (
            "bailongma.endpoint",
            "bailongma.enable_delegation",
            "codegen.candidates",
            "codegen.review",
            "gates.evolution",
            "gates.symbolic",
            "gates.metacognition",
        ):
            assert required in reg, required

    def test_settings_fusion_defaults_all_disabled(self, monkeypatch):
        from more_core.core.config import Settings

        s = Settings()
        assert s.bailongma_endpoint == ""
        assert s.bailongma_enable_delegation is False
        assert s.bailongma_bridge == "a2a"
        assert s.bailongma_observability_path == ""

    def test_settings_from_env_reads_fusion_vars(self, monkeypatch):
        from more_core.core.config import Settings

        monkeypatch.setenv("MORE_BAILONGMA_ENDPOINT", "http://x:9000")
        monkeypatch.setenv("MORE_BAILONGMA_BRIDGE", "a2a")
        monkeypatch.setenv("MORE_BAILONGMA_DELEGATION", "1")
        monkeypatch.setenv("MORE_BAILONGMA_OBS_DB", "/tmp/obs.sqlite")
        # Set at least one LLM provider so Settings() / from_env() validates
        monkeypatch.setenv("MORE_MOCK_PROVIDER", "")
        s = Settings.from_env()
        assert s.bailongma_endpoint == "http://x:9000"
        assert s.bailongma_enable_delegation is True
        assert s.bailongma_observability_path == "/tmp/obs.sqlite"
