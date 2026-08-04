"""MoRECore — runtime that wires every subsystem together.

This class is the single entry point users import.  It is intentionally
thin: it owns lifecycles and composition; domain logic lives in layers
and plugins.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any

from ..core.config import Settings
from ..core.errors import GovernanceError, MoREError
from ..core.event_bus import EventBus
from ..core.service_registry import ServiceRegistry
from ..core.types import (
    EngineStatus,
    LayerId,
    PerformanceMetrics,
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from ..evolution.archive import EvolutionArchive
from ..layers.base import Layer, LayerContext
from ..llm.provider import LLMRequest
from ..memory.store import MemoryStore
from ..evolution.benchmark import BenchmarkRunner, SimpleBenchmark
from ..router.layer_router import RoutingDecision
from ..tools.builtins import register_builtins
from ..core.request_context import RequestContext, set_context, clear_context
from ..core.unicode_utils import detect_language
from ..core.deliverable import (
    DeliverableContract,
    DeliverableKind,
    TaskExpectation,
    KillCriterion,
    KillSeverity,
)
from ..core.convergence import ConvergenceTracker
from ..metrics import get_collector
from ..incident_response import get_incident_manager
from ..hands.builtins import register_builtin_hands
from ..commands.registry import register_builtin_commands
from ..security.taint import TaintContext, TaintLabel
from ..zen_rules import ZENRulesEnforcer, get_enforcer

from ..hands.browser_hand import BrowserHand
from .bootstrap import init_capabilities, init_layers, init_services


class MoRECore:
    """Composition root for the MoRE Agent OS kernel."""

    # --- Attributes set by bootstrap factories (init_*) ---
    # Capabilities
    llm: Any
    task_model_router: Any
    sandbox: Any
    memory: Any
    ontology: Any
    metacognition: Any
    evolution_archive: Any
    evolution: Any
    tools: Any
    meta_orchestrator: Any | None
    dynamic_guardrails: Any | None
    # Layers & governance
    router: Any
    layers: dict[LayerId, Layer]
    audit: Any
    policy: Any
    # Services
    channels: Any
    cron: Any
    skill_manager: Any
    hand_registry: Any
    hands: Any
    commands: Any
    plugins: Any
    rbac: Any
    taint_tracker: Any
    output_filter: Any
    reconnect_manager: Any
    hand_persistence: Any
    hand_cloner: Any
    planner: Any
    token_predictor: Any
    workflows: Any
    plan_bridge: Any
    plan_monitor: Any
    deployment_manager: Any
    session_manager: Any
    # Post-bootstrap wiring
    _rate_limiter: Any
    _request_cache: Any
    _llm_circuit_breaker: Any
    _metrics: Any
    _incident_manager: Any
    reasoning_router: Any
    # Start-time (set in start())
    benchmark_runner: Any
    # v3.0
    model_aliases: Any
    # Hot reloader
    _hot_reloader: Any

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger("more_core")

        # Infrastructure
        self.registry = ServiceRegistry()
        self.event_bus = EventBus()

        # Project root for file operations
        self.project_root: Path | None = None
        if settings.project_root:
            self.project_root = Path(settings.project_root).resolve()

        # ---- Boot subsystems via extracted factories ----
        caps = init_capabilities(settings)
        for k, v in caps.items():
            setattr(self, k, v)

        layers_and_gov = init_layers(settings)
        for k, v in layers_and_gov.items():
            setattr(self, k, v)

        svc = init_services(settings)
        for k, v in svc.items():
            setattr(self, k, v)

        # -- Post-bootstrap wiring --
        # Backward-compatible underscored aliases for orchestration code
        self._rate_limiter = svc["rate_limiter"]
        self._request_cache = svc["request_cache"]
        self._llm_circuit_breaker = svc["llm_circuit_breaker"]
        # Metrics & incidents (from singleton getters)
        self._metrics = get_collector()
        self._incident_manager = get_incident_manager()

        # Reasoning & Model Aliases
        self.reasoning_router = self.task_model_router.reasoning_router

        # ── v3.0: Wire Meta-Orchestrator with LayerRouter ─────────────────
        # Post-bootstrap: MetaOrchestrator was created without router;
        # now that the LayerRouter is available, wire it in.
        if hasattr(self, "meta_orchestrator") and self.meta_orchestrator is not None:
            self.meta_orchestrator._layer_router = self.router
            self.logger.info("Meta-Orchestrator v3.0 wired with LayerRouter")

        self._start_time = time.time()

        self._register_services()

    # -- service registry ---------------------------------------------------

    def _register_services(self) -> None:
        """Register core subsystems so ``registry.stats()`` reflects real state.

        Each entry is keyed by the MoRECore attribute that owns the subsystem.
        Services that failed to boot (attribute is None) are skipped.
        """
        from ..core.types import EngineStatus, ServiceMetadata
        from ..version import __version__ as more_version

        services: dict[str, tuple[object, str, list[str]]] = {
            "llm": (self.llm, "llm", ["generate", "fallback", "cache"]),
            "router": (self.router, "layers", ["route", "pipeline"]),
            "memory": (self.memory, "capabilities", ["store", "recall"]),
            "evolution": (self.evolution, "capabilities", ["dgm", "archive", "benchmark"]),
            "sandbox": (self.sandbox, "capabilities", ["isolate", "execute"]),
            "ontology": (self.ontology, "capabilities", ["constraints", "validate"]),
            "metacognition": (self.metacognition, "capabilities", ["monitor", "reflect"]),
            "tools": (self.tools, "capabilities", ["registry", "dispatch"]),
            "channels": (self.channels, "services", ["adapters"]),
            "cron": (self.cron, "services", ["schedule", "trigger"]),
            "skills": (self.skill_manager, "services", ["browse", "code", "config"]),
            "hands": (self.hands, "services", ["registry", "execute"]),
            "plugins": (self.plugins, "services", ["discover", "activate"]),
            "security": (self.rbac, "services", ["rbac", "taint", "output_filter"]),
            "workflows": (self.workflows, "services", ["engine", "runs"]),
            "planning": (self.planner, "services", ["plan", "monitor", "predict"]),
        }
        for name, (owner, provider, caps) in services.items():
            if owner is None:
                continue
            self.registry.register(
                ServiceMetadata(
                    name=name,
                    version=more_version,
                    provider=provider,
                    status=EngineStatus.IDLE,
                    capabilities=caps,
                )
            )

    # -- factories ---------------------------------------------------------

    @classmethod
    def from_env(cls) -> "MoRECore":
        return cls(Settings.from_env())

    @staticmethod
    def _create_memory(settings: Settings) -> MemoryStore:
        db = os.getenv("MORE_MEMORY_DB")
        if db:
            from ..memory.sqlite_store import SQLiteMemoryStore

            return SQLiteMemoryStore(db)
        return MemoryStore()

    @staticmethod
    def _create_evolution_archive(settings: Settings) -> EvolutionArchive:
        db = os.getenv("MORE_EVOLUTION_DB")
        if db:
            from ..evolution.sqlite_archive import SQLiteEvolutionArchive

            return SQLiteEvolutionArchive(db)
        return EvolutionArchive()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        await self.event_bus.start()
        register_builtins(self.tools, self)
        # Wire benchmark runner into DGM for evaluation loop
        self.benchmark_runner = BenchmarkRunner(self)
        self.benchmark_runner.register(SimpleBenchmark())
        self.evolution.set_runner(self.benchmark_runner)
        self.plugins.discover()
        for md in self.plugins.list():
            await self.plugins.activate(md.name, self)
        register_builtin_hands(self.hand_registry)
        # Register Browser Hand
        _bh = BrowserHand()
        self.hand_registry.register(BrowserHand, _bh.manifest)
        register_builtin_commands(self.commands)
        await self.cron.start()
        from ..version import __version__

        for _md in self.registry.list_all():
            self.registry.set_status(_md.name, EngineStatus.RUNNING)

        self.audit.log(actor="system", action="start", entity="core", version=__version__)

    async def stop(self) -> None:
        # Deactivate in reverse dependency order: dependents first
        active = list(self.plugins.active())
        # Build reverse-dependency graph
        deps = {md.name: set(md.dependencies) for md in active}
        deactivated = set()
        remaining = set(d.name for d in active)
        while remaining:
            # Find plugins with no remaining dependents
            dep_on_remaining = {n: deps[n] & remaining for n in remaining}
            ready = [n for n in remaining if not dep_on_remaining.get(n)]
            if not ready:
                # Circular dependency — force deactivate remaining
                self.logger.warning(
                    "circular plugin dependencies, force-deactivating: %s", remaining
                )
                ready = list(remaining)
            for name in ready:
                try:
                    await self.plugins.deactivate(name)
                except Exception as exc:
                    self.logger.warning("deactivate %s failed: %s", name, exc)
                remaining.discard(name)
                deactivated.add(name)
        await self.hands.stop_all()
        await self.cron.stop()
        await self.channels.stop_all()
        await self.event_bus.stop()
        # Close LLM provider connection pools
        await self.llm.close()
        # Close persistent backends if applicable
        if hasattr(self.memory, "close"):
            self.memory.close()
        if hasattr(self.evolution_archive, "close"):
            self.evolution_archive.close()
        self.audit.log(actor="system", action="stop", entity="core")

    # -- extension points --------------------------------------------------

    def replace_layer(self, layer: Layer) -> None:
        """Install a plugin-provided layer implementation."""
        self.layers[layer.layer_id] = layer

    def get_layer(self, layer_id: LayerId) -> Layer:
        return self.layers[layer_id]

    def get_cache_stats(self) -> Any:
        return self._request_cache.stats()

    def get_rate_limiter_stats(self) -> dict[str, Any]:
        return {"rate_limiter": "token_bucket", "config": {"burst": self._rate_limiter._burst}}

    # -- execution ---------------------------------------------------------

    async def execute(self, request: TaskRequest) -> TaskResult:
        start = time.perf_counter()

        # --- Correlation context for structured logging ---
        req_ctx = RequestContext(
            task_id=request.id,
            actor=request.context.get("actor", "anonymous"),
        )
        token = set_context(req_ctx)

        # --- Rate limiting ---
        if not await self._rate_limiter.acquire():
            clear_context(token)
            self._metrics.record_request(0.0, False)
            return TaskResult(
                task_id=request.id,
                layer=LayerId.L0,
                status=TaskStatus.REJECTED,
                output="rate limit exceeded — retry after a short delay",
                performance=PerformanceMetrics(total_duration_ms=0.0),
            )

        # --- Task-level result cache (skip full pipeline for repeated queries) ---
        # Full-query hash key avoids collisions from the old first-512-chars key.
        cache_key = f"{request.type.value}|{hashlib.sha256(request.query.encode('utf-8')).hexdigest()}"
        cached = await self._request_cache.get(cache_key, "task")
        if cached is not None:
            clear_context(token)
            self._metrics.record_request(0.0, True)
            return TaskResult(
                task_id=request.id,
                layer=LayerId.L0,
                status=TaskStatus.SUCCESS,
                output=cached,
                performance=PerformanceMetrics(total_duration_ms=0.0),
            )

        # --- Taint tracking: mark query as USER_INPUT (request-scoped) ---
        taint = self.taint_tracker.scope(request.id)
        try:
            taint.track("query", request.query, TaintLabel.USER_INPUT, "api")

            available = set(self.llm.list_providers()) if self.llm else set()

            # ── v3.0 Meta-Orchestrator spectral routing ─────────────────
            # When Meta-Orchestrator is active it fully overrides the
            # pipeline decision, so the base LayerRouter pass is skipped
            # (avoids duplicate keyword classification per request).
            meta_decision = None
            guardrail_config = None
            if hasattr(self, "meta_orchestrator") and self.meta_orchestrator is not None:
                meta_decision = self.meta_orchestrator.route(
                    request.type,
                    request.query,
                    context=request.context,
                    require_metacognitive=request.require_metacognitive_monitoring,
                )
                # Override pipeline with spectral decision
                decision = RoutingDecision(
                    pipeline=meta_decision.pipeline,
                    reasoning=meta_decision.reasoning,
                )
                # Compute dynamic guardrails
                if hasattr(self, "dynamic_guardrails") and self.dynamic_guardrails is not None:
                    guardrail_config = self.dynamic_guardrails.adjust(
                        u=meta_decision.uncertainty_assessment.aggregated_u,
                        criticality=request.context.get("criticality", 0.5),
                        hints=meta_decision.guardrail_hints,
                    )
                    # Apply guardrail budget to request context
                    request.context["guardrail_config"] = guardrail_config.to_dict()
                    request.context["v3_mode"] = meta_decision.mode
                    self.logger.debug(
                        "v3.0 DynamicGuardrails applied: %s",
                        guardrail_config.reasoning,
                    )
            else:
                decision = self.router.route(request, available_providers=available)

            actor = request.context.get("actor", "anonymous")
            ctx = LayerContext(core=self, request=request, user_id=actor)
            await self.event_bus.publish(
                "task.started",
                data={
                    "id": request.id,
                    "type": request.type.value,
                    "pipeline": [layer.value for layer in decision.pipeline],
                },
                source="orchestrator",
            )
            self.audit.log(
                actor=request.context.get("actor", "anonymous"),
                action="execute_start",
                entity="task",
                task_id=request.id,
                task_type=request.type.value,
                query=request.query[:512],
                pipeline=[layer.value for layer in decision.pipeline],
            )

            output: Any = ""
            status = TaskStatus.SUCCESS

            # --- ZEN Rules enforcement (pre-execution) ---
            zen = get_enforcer()
            actor = request.context.get("actor", "anonymous")
            if zen.check_violation("ZEN-01", {"actor": actor, "task_id": request.id}):
                self.audit.log(
                    actor=actor,
                    action="zen_violation",
                    entity="task",
                    task_id=request.id,
                    rule="ZEN-01",
                )
            if zen.check_violation("ZEN-19", {"query": request.query, "task_id": request.id}):
                self.audit.log(
                    actor=actor,
                    action="zen_violation",
                    entity="task",
                    task_id=request.id,
                    rule="ZEN-19",
                )
                self._metrics.record_request(0.0, False)
                return TaskResult(
                    task_id=request.id,
                    layer=LayerId.L0,
                    status=TaskStatus.REJECTED,
                    output="rejected: ZEN-19 absolute prohibition — query contains forbidden operations",
                    performance=PerformanceMetrics(total_duration_ms=0.0),
                )

            # ── v2: 解析产出物契约与业务预期 ──────────────────
            expectation = self._resolve_expectation(request)
            convergence_tracker = ConvergenceTracker(
                contract=expectation.contract,
                kill_criteria=expectation.kill_criteria,
            )

            try:
                self.policy.check(request)
                await asyncio.wait_for(
                    self._run_pipeline(decision, ctx, convergence_tracker),
                    timeout=request.timeout_s,
                )
                output = ctx.scratch.get("_l0_output", "")
            except asyncio.TimeoutError:
                status = TaskStatus.FAILED
                output = f"task timed out after {request.timeout_s}s"
            except GovernanceError as exc:
                status = TaskStatus.REJECTED
                output = f"rejected: {exc}"
            except MoREError as exc:
                status = TaskStatus.FAILED
                output = f"failed: {exc}"
            except Exception as exc:  # unexpected
                self.logger.exception("task %s crashed", request.id)
                status = TaskStatus.FAILED
                output = f"internal error: {exc}"

            try:
                result = await self._complete_task(
                    request=request,
                    ctx=ctx,
                    status=status,
                    output=output,
                    start=start,
                    taint=taint,
                    actor=actor,
                    zen=zen,
                    convergence_tracker=convergence_tracker,
                    expectation=expectation,
                    cache_key=cache_key,
                )
            except Exception as exc:
                self.logger.exception("task %s post-processing crashed", request.id)
                result = TaskResult(
                    task_id=request.id,
                    layer=LayerId.L0,
                    status=TaskStatus.FAILED,
                    output=f"internal error: {exc}",
                    performance=PerformanceMetrics(
                        total_duration_ms=(time.perf_counter() - start) * 1000
                    ),
                )
        finally:
            taint.cleanup()
            clear_context(token)
        return result

    async def _complete_task(
        self,
        *,
        request: TaskRequest,
        ctx: LayerContext,
        status: TaskStatus,
        output: Any,
        start: float,
        taint: TaintContext,
        actor: str,
        zen: ZENRulesEnforcer,
        convergence_tracker: ConvergenceTracker,
        expectation: TaskExpectation,
        cache_key: str,
    ) -> TaskResult:
        """Build the final TaskResult and run post-processing.

        Filtering, deliverable/convergence assessment, event publishing,
        audit logging and caching.  A failure in any of these steps must
        not escape ``execute()`` — the caller wraps this in a try/except
        and converts it to a FAILED result.
        """
        total_ms = (time.perf_counter() - start) * 1000
        performance = PerformanceMetrics(
            total_duration_ms=total_ms,
            tokens_used=sum(s.input_tokens + s.output_tokens for s in ctx.accumulated_steps),
            layer_transitions=max(0, len(ctx.accumulated_steps) - 1),
        )
        # --- ZEN-17: LLM output safety check ---
        if status == TaskStatus.SUCCESS and output:
            if zen.check_violation("ZEN-17", {"output": str(output), "task_id": request.id}):
                self.audit.log(
                    actor=actor,
                    action="zen_violation",
                    entity="task",
                    task_id=request.id,
                    rule="ZEN-17",
                )

        # Apply output filtering to scrub PII / sensitive data before delivery
        filtered_output = self.output_filter.filter(str(output))
        # Mark the query's output as sanitized after passing output_filter
        taint.sanitize("query", "output_filter")

        # ── v2: 产出物完整性评估 ────────────────────────
        # Single-scan assessment: deliverable check + convergence score
        # computed together, so record() skips its own rescan.
        deliverable_complete = False
        deliverable_missing: list[str] = []
        convergence_score = 0.5
        if filtered_output:
            deliverable_complete, deliverable_missing, convergence_score = (
                ConvergenceTracker.assess(str(filtered_output), expectation.contract)
            )
        convergence_dict = (
            convergence_tracker.record(
                len(ctx.accumulated_steps),
                str(filtered_output),
                completeness=convergence_score,
            ).to_dict()
            if filtered_output
            else None
        )

        # v2: 收敛性降级 — 产出物不完整时标记为 PARTIAL
        if status == TaskStatus.SUCCESS and not deliverable_complete:
            if deliverable_missing:
                self.logger.warning(
                    "task %s 产出物不完整，缺失维度: %s",
                    request.id,
                    deliverable_missing,
                )
            # 关键维度缺失时降级
            critical_dims = {"core_output", "reasoning"}
            if any(d in deliverable_missing for d in critical_dims):
                status = TaskStatus.PARTIAL

        result = TaskResult(
            task_id=request.id,
            layer=ctx.accumulated_steps[-1].layer if ctx.accumulated_steps else LayerId.L0,
            status=status,
            output=filtered_output,
            reasoning_chain=list(ctx.accumulated_steps),
            performance=performance,
            calibration=ctx.scratch.get("calibration"),
            deliverable_complete=deliverable_complete,
            deliverable_missing=deliverable_missing,
            convergence_report=convergence_dict,
        )

        await self.event_bus.publish(
            "task.completed",
            data={"id": request.id, "status": status.value, "duration_ms": total_ms},
            source="orchestrator",
        )
        self.audit.log(
            actor=request.context.get("actor", "anonymous"),
            action="execute_end",
            entity="task",
            task_id=request.id,
            status=status.value,
            duration_ms=total_ms,
        )
        # --- Taint check: verify output is trusted before delivery ---
        if status == TaskStatus.SUCCESS and not taint.check("query"):
            self.logger.warning("taint violation: untrusted output for task %s", request.id)
            self.audit.log(
                actor=actor, action="taint_violation", entity="task", task_id=request.id
            )

        self._metrics.record_request(total_ms, status == TaskStatus.SUCCESS)
        # Cache successful results for future identical queries
        if status == TaskStatus.SUCCESS and output:
            await self._request_cache.set(cache_key, "task", str(output))
        return result

    def _resolve_expectation(self, request: TaskRequest) -> TaskExpectation:
        """解析任务请求中的业务预期。

        优先级:
        1. request.expectation (显式指定的完整预期)
        2. request.deliverable_kind (按类型匹配默认契约)
        3. 通用默认 (无约束)
        """
        # 优先使用显式指定的预期
        if request.expectation:
            contract_data = request.expectation.get("contract", {})
            kind_str = contract_data.get("kind", "custom")
            kind = (
                DeliverableKind(kind_str)
                if kind_str in (d.value for d in DeliverableKind)
                else DeliverableKind.CUSTOM
            )
            contract = DeliverableContract(
                kind=kind,
                required_dimensions=contract_data.get("required_dimensions", []),
                quality_gates=contract_data.get("quality_gates", {}),
                acceptance_criteria=contract_data.get("acceptance_criteria", []),
                description=contract_data.get("description", ""),
            )
            kill_criteria = [
                KillCriterion(
                    condition=kc.get("condition", ""),
                    severity=KillSeverity(kc.get("severity", "warning")),
                    timeline=kc.get("timeline", ""),
                    trigger=kc.get("trigger", ""),
                    fallback=kc.get("fallback", ""),
                )
                for kc in request.expectation.get("kill_criteria", [])
            ]
            return TaskExpectation(
                contract=contract,
                kill_criteria=kill_criteria,
                target_confidence=request.expectation.get("target_confidence", 60.0),
                max_iterations=request.expectation.get("max_iterations", 10),
                timeout_s=request.expectation.get("timeout_s", request.timeout_s),
            )

        # 按 deliverable_kind 匹配默认契约
        if request.deliverable_kind:
            try:
                kind = DeliverableKind(request.deliverable_kind)
                return TaskExpectation.default_for(kind)
            except ValueError:
                self.logger.warning("未知的 deliverable_kind: %s", request.deliverable_kind)

        # 通用默认: 无契约约束
        return TaskExpectation()

    async def _run_pipeline(
        self,
        decision: RoutingDecision,
        ctx: LayerContext,
        convergence_tracker: "ConvergenceTracker | None" = None,
    ) -> None:
        """Execute the layer pipeline; extracted to support timeout wrapping.

        v2 增强: 支持收敛性追踪和提前终止。
        """
        for layer_id in decision.pipeline:
            await self.event_bus.publish(
                "layer.started",
                data={"task_id": ctx.request.id, "layer": layer_id.value},
                source="orchestrator",
            )
            result = await self.layers[layer_id].run(ctx)

            # ── v2: 收敛性追踪 ─────────────────────────────
            if convergence_tracker and result.output:
                step_count = len(ctx.accumulated_steps) + 1
                conv_report = convergence_tracker.record(
                    step_count,
                    str(result.output),
                )
                if conv_report.should_terminate:
                    self.logger.warning(
                        "task %s 收敛性告警 layer=%s state=%s — 提前终止管道",
                        ctx.request.id,
                        layer_id.value,
                        conv_report.state.value,
                    )
                    self.audit.log(
                        actor=ctx.request.context.get("actor", "anonymous"),
                        action="convergence_terminate",
                        entity="task",
                        task_id=ctx.request.id,
                        layer=layer_id.value,
                        convergence_state=conv_report.state.value,
                    )
                    ctx.scratch["_l0_output"] = result.output
                    ctx.scratch["_convergence_terminated"] = True
                    return

            await self.event_bus.publish(
                "layer.completed",
                data={
                    "task_id": ctx.request.id,
                    "layer": layer_id.value,
                    "step": ctx.accumulated_steps[-1].model_dump() if ctx.accumulated_steps else {},
                },
                source="orchestrator",
            )
            if layer_id == LayerId.L0:
                ctx.scratch["_l0_output"] = result.output

    # -- streaming execution ---------------------------------------------------

    async def stream_execute(self, request: TaskRequest) -> AsyncIterator[str]:
        """Execute a task and yield tokens via async generator (SSE)."""
        import json

        start = time.perf_counter()

        # Rate limiting
        if not await self._rate_limiter.acquire():
            yield f"data: {json.dumps({'error': 'rate limit exceeded'})}\n\n"
            return

        # --- Taint tracking: mark query as USER_INPUT (request-scoped) ---
        taint = self.taint_tracker.scope(request.id)
        try:
            taint.track("query", request.query, TaintLabel.USER_INPUT, "api")

            available = set(self.llm.list_providers()) if self.llm else set()
            decision = self.router.route(request, available_providers=available)
            actor_s = request.context.get("actor", "anonymous")
            ctx = LayerContext(core=self, request=request, user_id=actor_s)

            # Emit pipeline info
            yield f"data: {json.dumps({'event': 'pipeline', 'layers': [lid.value for lid in decision.pipeline], 'task_id': request.id})}\n\n"

            try:
                self.policy.check(request)
            except GovernanceError as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
                return

            # Run pipeline up to L0 — layers populate ctx.scratch with
            # difficulty, plan, annotations, temperature, tokens, etc.
            # that L0's streaming generation will consume.
            for layer_id in decision.pipeline:
                if layer_id == LayerId.L0:
                    break
                result = await self.layers[layer_id].run(ctx)
                step_info = {"layer": layer_id.value, "description": result.description}
                yield f"data: {json.dumps({'event': 'layer_done', **step_info})}\n\n"

            # Stream L0 execution — use the same ctx.scratch that L4/L3/L1
            # populated, so code detection / plan / annotations are preserved.
            from ..layers.l0_execution import ExecutionLayer, _CODE_SYSTEM_PROMPTS, _SYSTEM_PROMPTS
            from ..core.types import TaskType

            is_code = request.type in (
                TaskType.CODE_GENERATION,
                TaskType.CODE_DEBUGGING,
                TaskType.CODE_TESTING,
                TaskType.CODE_REVIEW,
            )
            lang = detect_language(request.query)
            if is_code:
                system = _CODE_SYSTEM_PROMPTS.get(lang, _CODE_SYSTEM_PROMPTS.get("en", ""))
            else:
                system = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PROMPTS.get("en", ""))

            # Inject L3 annotations (same as the full execute path)
            ann = ctx.scratch.get("inference_annotations", {})
            if ann:
                guidance = ExecutionLayer._build_annotation_guidance(ann, request.type)
                if guidance:
                    system = system + "\n\n" + guidance

            # Build prompt via the unified builder (same as full execute path)
            plan = ctx.scratch.get("plan")
            secure_prompt = ExecutionLayer._build_prompt(
                query=request.query,
                plan=plan,
                output_filter=getattr(self, "output_filter", None),
            )

            # Respect L1's temperature / max_tokens overrides
            temperature = request.context.get("temperature", 0.7)
            max_tokens = request.context.get("max_tokens", 4096 if is_code else 2048)

            llm_req = LLMRequest(
                prompt=secure_prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Stream tokens — accumulate for final full-output filtering.
            # Per-token filtering is best-effort; PII crossing token boundaries
            # can only be caught by filtering the complete output.
            total_tokens = 0
            full_output = ""
            async for token in self.llm.stream(llm_req):
                total_tokens += 1
                filtered_token = self.output_filter.filter(token)
                full_output += token
                yield f"data: {json.dumps({'token': filtered_token})}\n\n"

            # Post-stream: apply full output filter and emit correction warnings
            filtered_full = self.output_filter.filter(full_output)
            if filtered_full != full_output:
                self.logger.info(
                    "stream_execute: full-output filter caught %d chars of PII missed by per-token filter",
                    len(full_output) - len(filtered_full),
                )
                yield f"data: {json.dumps({'event': 'filtered', 'note': 'post-stream PII scrubbing applied'})}\n\n"

            # Mark output as sanitized after streaming + full filtering
            taint.sanitize("query", "output_filter_stream")
            # Verify taint chain integrity
            if not taint.check("query"):
                self.logger.warning("taint violation in stream_execute for task %s", request.id)
                yield f"data: {json.dumps({'event': 'taint_warning', 'note': 'untrusted output detected'})}\n\n"

            # Emit completion
            elapsed = (time.perf_counter() - start) * 1000
            yield f"data: {json.dumps({'event': 'done', 'tokens': total_tokens, 'duration_ms': round(elapsed, 1)})}\n\n"
        finally:
            taint.cleanup()

    # -- MCP Server integration ---------------------------------------------------

    @property
    def mcp_server(self) -> Any:
        """Lazy-init MCP Server — exposes MoRE tools via MCP protocol."""
        if not hasattr(self, "_mcp_server_instance"):
            from ..mcp.server import MCPServer
            from ..mcp.protocol import ToolCallResult
            from ..version import __version__

            srv = MCPServer("QNMing MoRE OS", __version__)
            for tool in self.tools.list_tools():
                t = tool  # capture for closure

                async def _handler(args: Any, _t: Any = t) -> Any:
                    try:
                        result = await self.tools.invoke(_t.name, args)
                        return ToolCallResult(
                            content=[{"type": "text", "text": str(result.output)}],
                            isError=not result.success,
                        )
                    except Exception as e:
                        return ToolCallResult(
                            content=[{"type": "text", "text": str(e)}],
                            isError=True,
                        )

                srv.register_tool(
                    name=t.name,
                    description=t.description,
                    input_schema=t.parameters_schema,
                    handler=_handler,
                )
            srv.register_resource(
                uri="more://system/health", name="Health", description="MoRE OS health status"
            )
            srv.register_resource(
                uri="more://system/plugins", name="Plugins", description="Active plugins"
            )
            srv.register_resource(
                uri="more://hands/registry", name="Hands", description="Registered hands"
            )
            self._mcp_server_instance = srv
        return self._mcp_server_instance

    @property
    def mcp_client(self) -> Any:
        """Lazy-init MCP client."""
        if not hasattr(self, "_mcp_client"):
            from ..mcp.client import MCPClient

            self._mcp_client = MCPClient()
        return self._mcp_client

    # -- A2A Agent-to-Agent integration -------------------------------------------

    @property
    def a2a_server(self) -> Any:
        """Lazy-init A2A Server — handles Agent-to-Agent task delegation."""
        if not hasattr(self, "_a2a_server_instance"):
            from ..a2a.client import A2AServer, create_agent_card, A2ATaskState

            card = create_agent_card(
                name="QNMing MoRE OS",
                description="Neuro-Symbolic Metacognitive Self-Evolving Agent OS",
                url="http://localhost:8011",
                skills=["nlp", "code_gen", "reasoning", "plugin_exec", "multi_agent"],
            )
            srv = A2AServer(card)

            async def _a2a_handler(task: Any) -> Any:
                from ..core.types import TaskRequest, TaskType, TaskStatus

                text = ""
                for m in task.messages:
                    t = m.content.get("text", "")
                    if t:
                        text = t
                        break
                if not text:
                    task.state = A2ATaskState.FAILED
                    return task
                req = TaskRequest(type=TaskType.NLP_TASK, query=text)
                result = await self.execute(req)
                task.state = (
                    A2ATaskState.COMPLETED
                    if result.status == TaskStatus.SUCCESS
                    else A2ATaskState.FAILED
                )
                return task

            srv.set_task_handler(_a2a_handler)
            self._a2a_server_instance = srv
        return self._a2a_server_instance

    # -- LLM call with circuit breaker (used by layers) -----------------------

    async def llm_generate_safe(self, request: Any) -> Any:
        """LLM generate wrapped with circuit breaker for fault tolerance."""
        return await self._llm_circuit_breaker.call(self.llm.generate, request)
