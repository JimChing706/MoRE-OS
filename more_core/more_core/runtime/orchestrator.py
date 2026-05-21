"""MoRECore — runtime that wires every subsystem together.

This class is the single entry point users import.  It is intentionally
thin: it owns lifecycles and composition; domain logic lives in layers
and plugins.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..core.errors import GovernanceError, MoREError
from ..core.event_bus import EventBus
from ..core.service_registry import ServiceRegistry
from ..core.types import (
    LayerId,
    PerformanceMetrics,
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from ..evolution.archive import EvolutionArchive
from ..evolution.dgm import DGMEngine
from ..governance.audit import AuditLogger
from ..governance.policy import PolicyEnforcer
from ..layers import (
    CognitionLayer,
    EvolutionLayer,
    ExecutionLayer,
    MetacognitionLayer,
    OrchestrationLayer,
    SymbolicLayer,
)
from ..layers.base import Layer, LayerContext
from ..llm.manager import LLMManager
from ..llm.task_router import TaskModelRouter
from ..memory.store import MemoryStore
from ..metacognition.metacognition import MetacognitionService
from ..ontology.engine import OntologyEngine
from ..plugins.manager import PluginManager
from ..evolution.benchmark import BenchmarkRunner, SimpleBenchmark
from ..router.layer_router import LayerRouter, RoutingDecision
from ..sandbox.linux_sandbox import create_sandbox
from ..tools.builtins import register_builtins
from ..tools.registry import ToolRegistry
from ..optimization import RequestCache, CacheConfig, RateLimiter, CircuitBreaker
from ..core.request_context import RequestContext, set_context, clear_context
from ..metrics import get_collector
from ..incident_response import get_incident_manager
from ..hands.registry import HandRegistry
from ..hands.manager import HandManager
from ..hands.builtins import register_builtin_hands
from ..channels.manager import ChannelManager
from ..cron.scheduler import CronScheduler
from ..skills.base import SkillManager
from ..commands.registry import CommandRegistry, register_builtin_commands
from ..security.rbac import RBACManager
from ..security.taint import TaintTracker
from ..security.output_filter import OutputFilter
from ..llm.reasoning import ReasoningRouter
from ..llm.model_aliases import ModelAliasRegistry
from ..channels.reconnect import ReconnectManager
from ..hands.persistence import HandPersistence, HandCloner
from ..hands.browser_hand import BrowserHand
from ..workflows.engine import WorkflowEngine
from ..planning.coordinator import PlanCoordinator
from ..planning.token_predictor import TokenPredictor
from ..planning.workflow_bridge import PlanWorkflowBridge
from ..planning.plan_monitor import PlanMonitor
from ..deploy.manager import DeploymentManager
from .sessions import SessionManager


class MoRECore:
    """Composition root for the MoRE Agent OS kernel."""

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

        # Capabilities
        self.llm = LLMManager(settings.providers, settings.fallback_chain)
        self.task_model_router = TaskModelRouter(self.llm)
        self.sandbox = create_sandbox(
            timeout_s=settings.sandbox_timeout_s, memory_mb=settings.sandbox_memory_mb
        )
        self.memory = self._create_memory(settings)
        self.ontology = OntologyEngine()
        self.metacognition = MetacognitionService()
        self.evolution_archive = self._create_evolution_archive(settings)
        self.evolution = DGMEngine(self.evolution_archive)

        # Governance
        self.audit = AuditLogger(settings.audit_log_path)
        self.policy = PolicyEnforcer(settings)

        # Routing + layers
        self.router = LayerRouter(settings)
        self._layers: dict[LayerId, Layer] = {
            LayerId.L0: ExecutionLayer(),
            LayerId.L1: OrchestrationLayer(),
            LayerId.L2: EvolutionLayer(),
            LayerId.L3: SymbolicLayer(),
            LayerId.L4: CognitionLayer(),
            LayerId.L5: MetacognitionLayer(),
        }

        # Tools
        self.tools = ToolRegistry()

        # Plugins
        self.plugins = PluginManager(settings.plugin_dir)

        # Performance optimization
        self._request_cache = RequestCache(CacheConfig(
            max_size=settings.cache_max_size,
            ttl_seconds=settings.cache_ttl_seconds,
        ))
        self._rate_limiter = RateLimiter(
            rate=settings.rate_limit_rps,
            burst=settings.rate_limit_burst,
        )
        self._llm_circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
        )
        self._metrics = get_collector()
        self._incident_manager = get_incident_manager()

        # Channels, Cron, Skills, Hands, Commands
        self.channels = ChannelManager()
        self.cron = CronScheduler()
        self.skill_manager = SkillManager()
        self.hand_registry = HandRegistry()
        self.hands = HandManager(self.hand_registry, self.cron)
        self.commands = CommandRegistry()

        # Security
        self.rbac = RBACManager()
        self.taint_tracker = TaintTracker()
        self.output_filter = OutputFilter()

        # Reasoning & Model Aliases
        self.reasoning_router = ReasoningRouter()
        self.model_aliases = ModelAliasRegistry()

        # Channel Reconnect
        self.reconnect_manager = ReconnectManager()

        # Hand Persistence & Cloning
        self.hand_persistence = HandPersistence()
        self.hand_cloner = HandCloner(self.hands)

        # Planning, Workflows, Deployments, Sessions
        self.planner = PlanCoordinator()
        self.token_predictor = TokenPredictor()
        self.workflows = WorkflowEngine()
        self.plan_bridge = PlanWorkflowBridge(self.workflows, self.token_predictor)
        self.plan_monitor = PlanMonitor()
        self.deployment_manager = DeploymentManager()
        self.session_manager = SessionManager()
        self._start_time = time.time()

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
        self.audit.log(actor="system", action="start", entity="core", version=__version__)

    async def stop(self) -> None:
        for md in list(self.plugins.active()):
            try:
                await self.plugins.deactivate(md.name)
            except Exception as exc:  # pragma: no cover
                self.logger.warning("deactivate %s failed: %s", md.name, exc)
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
        self._layers[layer.layer_id] = layer

    def get_layer(self, layer_id: LayerId) -> Layer:
        return self._layers[layer_id]

    def get_cache_stats(self) -> dict:
        return self._request_cache.stats()

    def get_rate_limiter_stats(self) -> dict:
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
        cache_key = f"{request.type.value}|{request.query[:512]}"
        cached = self._request_cache.get(cache_key, "task")
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

        decision = self.router.route(request)
        ctx = LayerContext(core=self, request=request)
        await self.event_bus.publish(
            "task.started",
            data={"id": request.id, "type": request.type.value, "pipeline": [layer.value for layer in decision.pipeline]},
            source="orchestrator",
        )
        self.audit.log(
            actor=request.context.get("actor", "anonymous"),  # type: ignore[arg-type]
            action="execute_start",
            entity="task",
            task_id=request.id,
            task_type=request.type.value,
            pipeline=[layer.value for layer in decision.pipeline],
        )

        output: Any = ""
        status = TaskStatus.SUCCESS
        try:
            self.policy.check(request)
            await asyncio.wait_for(
                self._run_pipeline(decision, ctx),
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

        total_ms = (time.perf_counter() - start) * 1000
        performance = PerformanceMetrics(
            total_duration_ms=total_ms,
            tokens_used=sum(s.input_tokens + s.output_tokens for s in ctx.accumulated_steps),
            layer_transitions=max(0, len(ctx.accumulated_steps) - 1),
        )
        result = TaskResult(
            task_id=request.id,
            layer=ctx.accumulated_steps[-1].layer if ctx.accumulated_steps else LayerId.L0,
            status=status,
            output=str(output),
            reasoning_chain=list(ctx.accumulated_steps),
            performance=performance,
            calibration=ctx.scratch.get("calibration"),
        )

        await self.event_bus.publish(
            "task.completed",
            data={"id": request.id, "status": status.value, "duration_ms": total_ms},
            source="orchestrator",
        )
        self.audit.log(
            actor=request.context.get("actor", "anonymous"),  # type: ignore[arg-type]
            action="execute_end",
            entity="task",
            task_id=request.id,
            status=status.value,
            duration_ms=total_ms,
        )
        self._metrics.record_request(total_ms, status == TaskStatus.SUCCESS)
        # Cache successful results for future identical queries
        if status == TaskStatus.SUCCESS and output:
            self._request_cache.set(cache_key, "task", str(output))
        clear_context(token)
        return result

    async def _run_pipeline(
        self, decision: RoutingDecision, ctx: LayerContext
    ) -> None:
        """Execute the layer pipeline; extracted to support timeout wrapping."""
        for layer_id in decision.pipeline:
            await self.event_bus.publish(
                "layer.started",
                data={"task_id": ctx.request.id, "layer": layer_id.value},
                source="orchestrator",
            )
            result = await self._layers[layer_id].run(ctx)
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

    # -- LLM call with circuit breaker (used by layers) -----------------------

    async def llm_generate_safe(self, request: Any) -> Any:
        """LLM generate wrapped with circuit breaker for fault tolerance."""
        return await self._llm_circuit_breaker.call(self.llm.generate, request)
