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
    TaskType,
)
from ..evolution.archive import EvolutionArchive
from ..layers.base import Layer, LayerContext
from ..llm.model_aliases import ModelAliasRegistry
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
        # Public alias: layers resolve the incident manager via ctx.core (DI, TD-05)
        self.incident_manager = self._incident_manager

        # Reasoning & Model Aliases
        self.reasoning_router = self.task_model_router.reasoning_router
        self.model_aliases = ModelAliasRegistry()

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
        # 启动技能：注册 ≠ 可用。此前从不调用 start_all()，导致所有技能恒为
        # INACTIVE、health_check() 恒 False（/skills 面板全"未激活"）。
        try:
            await self.skill_manager.start_all()
        except Exception:  # pragma: no cover - 技能启动失败不得阻断启动
            self.logger.warning("skill start_all failed", exc_info=True)
        # R-4：技能出网可达性自检（DNS+TCP），结果落库并在看板/告警中暴露。
        # 可用 MORE_SKIP_SKILL_NETWORK_PREFLIGHT=1 跳过（测试/离线环境）。
        if os.getenv("MORE_SKIP_SKILL_NETWORK_PREFLIGHT") != "1":
            try:
                from ..governance import observability as _obs
                from ..skills.network_check import check_skill_network

                _net = await check_skill_network(self.skill_manager)
                _obs.record_skill_network(_net)
                for _w in _net.get("warnings") or []:
                    self.logger.warning("skill network preflight: %s", _w)
            except Exception:  # pragma: no cover - 自检失败不得阻断启动
                self.logger.warning("skill network preflight skipped", exc_info=True)
        # 生产效率事故修复：启动即校验 LLM 链路（模型名是否存在、兜底链是否完整）
        try:
            from ..llm.preflight import preflight_llm

            _pf = await preflight_llm(self.llm, list(getattr(self.llm, "_fallback", []) or []))
            self.llm_preflight = _pf.to_dict()
            # 预检快照落库 → 供 /metrics/providers 与看板消费（无效模型标识可告警）
            from ..governance import observability as _obs

            _obs.record_provider_health(self.llm_preflight)
            for _w in _pf.warnings:
                self.logger.warning("LLM preflight: %s", _w)
            if _pf.ok:
                self.logger.info("LLM preflight OK (chain=%s)", ",".join(_pf.chain_registered))
        except Exception as exc:  # pragma: no cover - 预检失败不阻断启动
            self.logger.warning("LLM preflight skipped: %s", exc)
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

    def resolve_pipeline(
        self,
        request: TaskRequest,
        *,
        available_providers: set[str] | None = None,
    ) -> tuple[RoutingDecision, Any]:
        """**唯一权威**的层管道解析入口。

        * 启用 Meta-Orchestrator 谱路由 → 采用其决策（`source="meta_orchestrator"`），
          基座 :class:`LayerRouter` 被跳过；
        * 未启用 → 回退基座 :class:`LayerRouter`（`source="router"`，advisory/fallback）。

        返回 ``(decision, meta_decision)``；回退时 ``meta_decision`` 为 ``None``。
        注意：深度模式只由 ``require_metacognitive_monitoring`` 触发——
        不能用 ``allow_self_improvement`` 触发，否则会出现
        "L5/L2 先自修改 → L3 才以 policy.metacog_review 拒绝" 的危险顺序。
        """
        if getattr(self, "meta_orchestrator", None) is not None:
            meta_decision = self.meta_orchestrator.route(
                request.type,
                request.query,
                context=request.context,
                require_metacognitive=request.require_metacognitive_monitoring,
            )
            return (
                RoutingDecision(
                    pipeline=list(meta_decision.pipeline),
                    reasoning=meta_decision.reasoning,
                    source="meta_orchestrator",
                ),
                meta_decision,
            )
        return (
            self.router.route(request, available_providers=available_providers),
            None,
        )

    async def execute(self, request: TaskRequest) -> TaskResult:
        start = time.perf_counter()

        # --- AUTO task-type resolution (zero-LLM keyword classification) ---
        # Normalize TaskType.AUTO into a concrete type up-front so the rest of
        # the pipeline (cache key, routing, meta-orchestrator) sees a real type.
        if request.type is TaskType.AUTO:
            self._resolve_auto_type(request)

        # --- R-03: 身份只信任凭证派生的 principal，不信任请求体 actor ---
        from ..security.principal import get_principal

        _trusted = get_principal()
        _claimed = str(request.context.get("actor") or "anonymous")
        if _trusted:
            if _claimed != _trusted:
                # 保留调用方自报值仅用于审计，不参与任何权限判断
                request.context["requested_actor"] = _claimed
            request.context["actor"] = _trusted
            actor_effective = _trusted
        else:
            actor_effective = _claimed

        # --- Correlation context for structured logging ---
        req_ctx = RequestContext(
            task_id=request.id,
            actor=actor_effective,
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

        # --- Task-level result cache（R-06 修复） ---
        # 旧键只含 type+query 哈希，导致：
        #   ① 不同主体（actor）共享同一份输出 → 跨主体数据复用；
        #   ② 同一需求无法重新生成（永久命中旧结果）；
        #   ③ 命中分支位于 ZEN/policy 校验之前 → 治理被短路。
        # 现在：键纳入主体；代码类任务默认禁用整任务缓存（必须可重生成）；
        # 且允许 context["no_cache"]=True 显式绕过。
        _code_task = request.type in (
            TaskType.CODE_GENERATION,
            TaskType.CODE_DEBUGGING,
            TaskType.CODE_TESTING,
        )
        _no_cache = bool(request.context.get("no_cache")) or _code_task
        cache_key = (
            f"{request.type.value}"
            f"|{hashlib.sha256(request.query.encode('utf-8')).hexdigest()}"
            f"|{str(request.context.get('actor') or 'anonymous')}"
        )
        cached = None if _no_cache else await self._request_cache.get(cache_key, "task")
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

            # ── 管道解析（唯一权威入口） ────────────────────────────
            # resolve_pipeline() 内部：Meta-Orchestrator 优先，否则回退基座路由。
            decision, meta_decision = self.resolve_pipeline(request, available_providers=available)
            guardrail_config = None
            if meta_decision is not None:
                # Compute dynamic guardrails from the spectral decision
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

            actor = str(request.context.get("actor") or "anonymous")
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
            actor = str(request.context.get("actor") or "anonymous")
            if zen.check_violation("ZEN-01", {"actor": actor, "task_id": request.id}):
                self.audit.log(
                    actor=actor,
                    action="zen_violation",
                    entity="task",
                    task_id=request.id,
                    rule="ZEN-01",
                )
            zen19_blocked = zen.check_violation(
                "ZEN-19", {"query": request.query, "task_id": request.id}
            )
            # 可观测性：前置护栏是"最前线"的治理门禁。每个请求都记一行
            # （通过/拦截），让治理拦截率拥有全量请求分母，而不是只看进 L3 的
            # 子集（谱路由会跳过 L3）。
            self._record_governance_event(
                request,
                layer="guardrail",
                blocked=zen19_blocked,
                rules=["zen_19_absolute_prohibition"] if zen19_blocked else [],
                violations=["query contains forbidden operations"] if zen19_blocked else [],
            )
            if zen19_blocked:
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
            except asyncio.CancelledError:
                # Provider-side cancellation (e.g. httpx internal timeout on a
                # hung local model) must surface as a structured FAILED result,
                # not escape as a bare 500.
                status = TaskStatus.FAILED
                output = "task cancelled by provider timeout"
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
                    no_cache=_no_cache,
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
        no_cache: bool = False,
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

        # ── 管道输出自检（advisory，不影响主流程） ──────────────
        # 复用 council.self_check 对推理链→最终输出的覆盖度做启发式审计，
        # 结果写入 TaskResult.metadata 供可观测/审计使用。
        self_check_report: dict[str, Any] | None = None
        try:
            if ctx.accumulated_steps and filtered_output:
                from ..council.self_check import run_pipeline_self_check

                report = run_pipeline_self_check(
                    ctx.accumulated_steps,
                    str(filtered_output),
                    task_type=request.type,
                )
                self_check_report = report.to_dict()
                if report.backfill_required:
                    self.audit.log(
                        actor="system",
                        action="self_check_backfill",
                        entity="task",
                        task_id=request.id,
                        coverage_pct=report.coverage_pct,
                        backfill_items=report.backfill_items,
                    )
        except Exception as exc:
            self.logger.warning("pipeline self-check failed for task %s: %s", request.id, exc)

        # ── 产出正确性闸门 + 交付可信度台账（P0 修复） ──────────────
        # 1) 代码类任务：确保"被验证的工件"就是"被交付的工件"。
        #    过滤器在 L0 沙箱验证之后才改写输出，历史上曾把 key=lambda 改写成
        #    [ENV_SECRET_REDACTED] 从而交付语法错误的代码（见审计报告 F-01/F-02）。
        #    这里做一次"过滤前 vs 过滤后"语法对比，若过滤破坏了原本合法的代码，
        #    则回退到过滤前工件（代码优先），并记录告警与审计事件。
        gate_report: Any = None
        metadata_verdict_conflict = False
        metadata_escalation_cause: dict[str, Any] | None = None
        delivery_status = "delivered" if status == TaskStatus.SUCCESS else "failed"
        delivery_reason = ""

        # G1（交付可信度交叉校验）：Codegen Controller 裁决 `escalated` 表示
        # 成功判据未满足（修复轮次耗尽 / 断言未过 / 评审拒绝）。此时绝不能把
        # 交付标成 delivered —— 否则台账与控制器结论互相矛盾。
        from ..codegen.delivery_policy import resolve_delivery_decision

        _verdict_decision = str((ctx.scratch.get("codegen_verdict") or {}).get("decision", ""))
        # 仅代码类任务受 Codegen Controller 约束：NLP/数据分析等任务的
        # verdict 不具业务含义，不能用它阻断交付（否则会大面积误伤）。
        _is_code_task = request.type in (
            TaskType.CODE_GENERATION,
            TaskType.CODE_DEBUGGING,
            TaskType.CODE_TESTING,
        )
        _cause = str(
            ((ctx.scratch.get("codegen_verdict") or {}).get("artifacts") or {}).get("cause", "")
        )
        _decision = resolve_delivery_decision(
            task_succeeded=(status == TaskStatus.SUCCESS),
            gates_passed=True,  # 闸门在下方单独校验（需要先跑 gates）
            verdict=_verdict_decision if _is_code_task else "",
            cause=_cause,
        )
        if _decision.status == "blocked" and delivery_status == "delivered":
            delivery_status = "blocked"
            delivery_reason = _decision.reason
            metadata_escalation_cause = {
                "cause": _decision.cause,
                "is_infra": _decision.is_infra,
                "needs_attention": _decision.needs_attention,
            }
            if status == TaskStatus.SUCCESS:
                status = TaskStatus.FAILED
            metadata_verdict_conflict = True
            self.audit.log(
                actor="system",
                action="delivery_blocked",
                entity="task",
                task_id=request.id,
                detail=delivery_reason,
            )
        if request.type in (
            TaskType.CODE_GENERATION,
            TaskType.CODE_DEBUGGING,
            TaskType.CODE_TESTING,
        ):
            from ..codegen.gates import run_gates

            raw_text = str(output or "")
            filtered_text = str(filtered_output or "")
            raw_gates = run_gates(raw_text, query=request.query)
            filtered_gates = run_gates(filtered_text, query=request.query)
            if raw_gates.passed and not filtered_gates.passed:
                self.logger.warning(
                    "output filter broke code for task %s — delivering pre-filter artifact",
                    request.id,
                )
                self.audit.log(
                    actor="system",
                    action="output_filter_corrupted_code",
                    entity="task",
                    task_id=request.id,
                    detail=filtered_gates.summary()[:300],
                )
                filtered_output = output
                filtered_gates = raw_gates
            gate_report = filtered_gates
            if not gate_report.passed:
                delivery_status = "blocked"
                delivery_reason = gate_report.summary()[:300]
                # D-1：闸门拦截同样要记录可聚合的原因（此前只记 reason，
                # 导致看板出现大量 unspecified）
                _failed_gates = [f.gate for f in gate_report.blocking_failures] or ["unknown"]
                metadata_escalation_cause = {
                    "cause": f"gate_{_failed_gates[0]}_failed",
                    "is_infra": False,
                    "needs_attention": True,
                    "failed_gates": _failed_gates,
                }
                if status == TaskStatus.SUCCESS:
                    status = TaskStatus.FAILED
                    self.logger.warning(
                        "delivery blocked by gates for task %s: %s", request.id, delivery_reason
                    )
                    self.audit.log(
                        actor="system",
                        action="delivery_blocked",
                        entity="task",
                        task_id=request.id,
                        detail=delivery_reason,
                    )

        metadata: dict[str, Any] = {}
        # D-4：分段耗时（含占比与总计），供延迟归因
        _stage_timings = ctx.scratch.get("stage_timings") or {}
        if _stage_timings:
            _total = sum(float(v) for v in _stage_timings.values()) or 1.0
            metadata["stage_timings"] = {
                "layers_ms": dict(_stage_timings),
                "total_ms": round(_total, 1),
                "share_pct": {
                    k: round(float(v) / _total * 100, 1) for k, v in _stage_timings.items()
                },
            }
        if metadata_escalation_cause:
            metadata["escalation"] = metadata_escalation_cause
        if metadata_verdict_conflict:
            metadata["verdict_conflict"] = {
                "codegen_verdict": _verdict_decision,
                "delivery_status": delivery_status,
                "note": "controller escalated → delivery blocked",
            }
        if gate_report is not None:
            metadata["delivery_gates"] = gate_report.to_dict()
        if self_check_report:
            metadata["self_check"] = self_check_report
        if "auto_resolved_type" in request.context:
            metadata["auto_resolved_type"] = request.context["auto_resolved_type"]
            metadata["auto_confidence"] = request.context["auto_confidence"]
        if ctx.scratch.get("codegen_verdict"):
            metadata["codegen_verdict"] = ctx.scratch["codegen_verdict"]

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
            metadata=metadata,
        )

        # ── 交付台账：每一次交付留痕（状态/权责/版本/哈希/裁决/闸门） ──
        try:
            from ..codegen.delivery_ledger import get_default_ledger

            _ledger = get_default_ledger()
            _ledger.record(
                task_id=request.id,
                status=delivery_status,
                task_type=request.type.value,
                reason=delivery_reason,
                cause=(metadata_escalation_cause or {}).get("cause", ""),
                is_infra=bool((metadata_escalation_cause or {}).get("is_infra", False)),
                stage_timings=(metadata.get("stage_timings") or {}).get("layers_ms", {}),
                artifact=str(filtered_output or ""),
                verdict=str((ctx.scratch.get("codegen_verdict") or {}).get("decision", "")),
                gates=(gate_report.to_dict() if gate_report is not None else {}),
                gates_passed=(gate_report.passed if gate_report is not None else True),
                actor=str(request.context.get("actor", "anonymous")),
                provider=str(request.context.get("provider", "")),
                model=str(request.context.get("model", "")),
                request_excerpt=str(request.query or ""),
            )
        except Exception as exc:  # pragma: no cover - 台账失败不得影响用户链路
            self.logger.warning("delivery ledger write failed for %s: %s", request.id, exc)

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
            self.audit.log(actor=actor, action="taint_violation", entity="task", task_id=request.id)

        self._metrics.record_request(total_ms, status == TaskStatus.SUCCESS)
        # Cache successful results for future identical queries
        # （被闸门拦截的产物不进入缓存，避免把坏结果扩散成"可复用"答案）
        if (
            status == TaskStatus.SUCCESS
            and output
            and delivery_status == "delivered"
            and not no_cache
        ):
            await self._request_cache.set(cache_key, "task", str(output))
        return result

    def _resolve_auto_type(self, request: TaskRequest) -> None:
        """Resolve ``TaskType.AUTO`` into a concrete type from the query text.

        Mutates ``request.type`` in place and records the classification in
        ``request.context`` so callers can observe what was decided.
        """
        from ..router.task_classifier import classify

        result = classify(request.query)
        request.type = result.task_type
        request.context["auto_resolved_type"] = result.task_type.value
        request.context["auto_confidence"] = result.confidence
        request.context["auto_matched_keywords"] = list(result.matched_keywords)
        self.logger.debug(
            "auto-classified task %s as %s (conf=%.2f)",
            request.id,
            result.task_type.value,
            result.confidence,
        )

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

    def _record_governance_event(
        self,
        request: TaskRequest,
        *,
        layer: str,
        blocked: bool,
        rules: list[str] | None = None,
        violations: list[str] | None = None,
    ) -> None:
        """Emit one governance evaluation row. Never raises (telemetry only)."""
        try:
            from ..governance import observability as _obs

            _obs.record_governance_event(
                request_id=request.id,
                layer=layer,
                task_type=request.type.value,
                blocked=blocked,
                strict=bool(getattr(self.settings, "strict_ontology", True)),
                rules=rules or [],
                violations=violations or [],
            )
        except Exception:  # pragma: no cover - telemetry must never break execution
            pass

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
            # D-4：阶段级分段计时 —— 让端到端延迟可归因到具体层
            _t0 = time.perf_counter()
            result = await self.layers[layer_id].run(ctx)
            _elapsed_ms = (time.perf_counter() - _t0) * 1000.0
            _timings = ctx.scratch.setdefault("stage_timings", {})
            _timings[layer_id.value] = round(_elapsed_ms, 1)

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

        # Resolve AUTO type so the code-detection branch below sees a real type.
        if request.type is TaskType.AUTO:
            self._resolve_auto_type(request)

        # Rate limiting
        if not await self._rate_limiter.acquire():
            yield f"data: {json.dumps({'error': 'rate limit exceeded'})}\n\n"
            return

        # --- Taint tracking: mark query as USER_INPUT (request-scoped) ---
        taint = self.taint_tracker.scope(request.id)
        try:
            taint.track("query", request.query, TaintLabel.USER_INPUT, "api")

            available = set(self.llm.list_providers()) if self.llm else set()
            # 统一权威入口：流式与非流式必须使用同一管道来源
            decision, _meta = self.resolve_pipeline(request, available_providers=available)
            actor_s = str(request.context.get("actor") or "anonymous")
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

                # ── Step-4 P2: task_type from A2A message metadata ──────
                # BaiLongma bridge sends content = {text, task_type, context}.
                # Older plain-text agents send just content.text; default
                # to NLP_TASK in that case to preserve backwards compat.
                text = ""
                task_type_hint: str | None = None
                context: dict[str, Any] = {}
                for m in task.messages:
                    body = m.content or {}
                    t = body.get("text", "") if isinstance(body, dict) else ""
                    if t:
                        text = t
                    if isinstance(body, dict):
                        # Prefer explicit task_type from first message that has one.
                        if task_type_hint is None and body.get("task_type"):
                            task_type_hint = str(body["task_type"])
                        if isinstance(body.get("context"), dict) and not context:
                            context = dict(body["context"])
                    # Also inspect message.metadata["task_type"] / qnm_origin
                    # which may be populated by chassis without rewriting body.
                    meta = m.metadata if isinstance(m.metadata, dict) else {}
                    if task_type_hint is None and meta.get("qnm_origin") == "delegate_v1":
                        if meta.get("task_type"):
                            task_type_hint = str(meta["task_type"])
                if not text:
                    task.state = A2ATaskState.FAILED
                    return task
                # Resolve TaskType from hint (allow both enum value strings and
                # raw member names — lenient so future chassis versions work).
                req_type = TaskType.NLP_TASK
                if task_type_hint:
                    for t in TaskType:
                        if (
                            t.value == task_type_hint
                            or t.name.lower() == task_type_hint.lower()
                            or str(t) == task_type_hint
                        ):
                            req_type = t
                            break
                req = TaskRequest(type=req_type, query=text, context=context)

                # ── Step-4 P2: background execution avoids HTTP timeout ──
                # tasks/send returns WORKING immediately; caller polls via
                # tasks/get.  Final COMPLETED / FAILED state is written back
                # to task.state + an agent-role message carries the output.
                task.state = A2ATaskState.WORKING

                async def _runner() -> None:
                    from ..a2a.client import A2AMessage
                    from ..core.deliverable import (
                        DeliverableContract,
                        DeliverableKind,
                        check_deliverable_contract,
                    )

                    try:
                        result = await self.execute(req)
                        # ── Step 4 Delivery Contract kill-switch integration ──
                        # Pick a DeliverableContract template based on task
                        # type; prefer explicit contract passed by caller
                        # via context.contract (allows customisation per
                        # request by a delegating chassis or L0 gate).
                        # Collect observations (step_count, timing, fatal
                        # errors) from context if the pipeline wrote them.
                        try:
                            ctx_contract = (
                                req.context.get("contract")
                                if isinstance(req.context, dict)
                                else None
                            )
                            if isinstance(ctx_contract, DeliverableContract):
                                contract = ctx_contract
                            else:
                                _kmap = {
                                    TaskType.CODE_GENERATION: DeliverableKind.CODE,
                                    TaskType.CODE_REVIEW: DeliverableKind.CODE,
                                    TaskType.ARCHITECTURE_DESIGN: DeliverableKind.ARCHITECTURE,
                                    TaskType.DATA_ANALYSIS: DeliverableKind.ANALYSIS,
                                    TaskType.NLP_TASK: DeliverableKind.EXPLANATION,
                                    TaskType.MATH_REASONING: DeliverableKind.DECISION,
                                }
                                _kind = _kmap.get(req_type, DeliverableKind.CUSTOM)
                                contract = DeliverableContract(kind=_kind)
                                # If the caller placed quality_gates into
                                # the context, merge them in so custom
                                # step/time budgets propagate.
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
                            _step_count = int(
                                getattr(result, "fix_iterations", 0)
                                or (
                                    int(req.context.get("fix_iterations", 0))
                                    if isinstance(req.context, dict)
                                    else 0
                                )
                            )
                            _fatal_errors = int(
                                req.context.get("_fatal_errors", 0)
                                if isinstance(req.context, dict)
                                else 0
                            )
                            _success_rate = (
                                req.context.get("_success_rate")
                                if isinstance(req.context, dict)
                                else None
                            )
                            # Extract output text for completeness check.
                            _output_text = ""
                            if isinstance(getattr(result, "data", None), dict):
                                _output_text = str(result.data.get("output", ""))
                            if not _output_text:
                                _data = getattr(result, "data", None)
                                _output_text = "" if _data is None else str(_data)
                            check_res = check_deliverable_contract(
                                contract,
                                output_text=_output_text,
                                step_count=_step_count,
                                elapsed_s=elapsed,
                                success_rate=_success_rate,
                                fatal_errors=_fatal_errors,
                            )
                            # Apply the contract verdict: override
                            # final_state and attach metadata.
                            if check_res.final_state == "FAILED":
                                final_state = A2ATaskState.FAILED
                            else:
                                final_state = (
                                    A2ATaskState.COMPLETED
                                    if result.status == TaskStatus.SUCCESS
                                    else A2ATaskState.FAILED
                                )
                            # Serialize contract check for observers.
                            try:
                                if not isinstance(task.metadata, dict):
                                    task.metadata = {}
                                task.metadata["deliverable_check"] = check_res.to_metadata()
                            except Exception:
                                pass
                        except Exception:
                            # Contract check is best-effort; never leak an
                            # error that would mask the real result.
                            final_state = (
                                A2ATaskState.COMPLETED
                                if result.status == TaskStatus.SUCCESS
                                else A2ATaskState.FAILED
                            )
                        task.state = final_state
                        # Add agent-role message with the final output; if
                        # the orchestrator returned a dict with `output` use
                        # that, otherwise just use str(result.data).
                        output_text = ""
                        if isinstance(getattr(result, "data", None), dict):
                            output_text = str(result.data.get("output", ""))
                        if not output_text:
                            data = getattr(result, "data", None)
                            output_text = "" if data is None else str(data)
                        msg = A2AMessage(
                            role="agent",
                            content={"text": output_text},
                            metadata={
                                "task_status": getattr(result, "status", TaskStatus.FAILED).value,
                            },
                        )
                        task.messages.append(msg)
                    except Exception as exc:  # pragma: no cover - defensive
                        task.state = A2ATaskState.FAILED
                        task.messages.append(
                            A2AMessage(
                                role="agent",
                                content={"text": f"Internal error: {exc!r}"},
                                metadata={"error": repr(exc)},
                            )
                        )

                import asyncio as _aio

                _aio.create_task(_runner())
                return task

            srv.set_task_handler(_a2a_handler)
            self._a2a_server_instance = srv
        return self._a2a_server_instance

    # -- LLM call with circuit breaker (used by layers) -----------------------

    async def llm_generate_safe(self, request: Any) -> Any:
        """LLM generate wrapped with circuit breaker for fault tolerance."""
        return await self._llm_circuit_breaker.call(self.llm.generate, request)
