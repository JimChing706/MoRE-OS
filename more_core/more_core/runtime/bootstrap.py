"""Bootstrap helpers for MoRECore subsystem initialisation.

Extracted from ``orchestrator.py`` to reduce the cognitive load of the
MoRECore constructor and make dependency boundaries explicit.

Each factory method initialises a cohesive group of subsystems so that
future work can extract them into independent coordinator types.
"""

from __future__ import annotations

import logging
import os
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.config import Settings
    from ..evolution.archive import EvolutionArchive

_log = logging.getLogger(__name__)


def _make_council_complete_fn(llm: Any) -> Any:
    """Build an adapter so CouncilOrchestrator can call llm.generate(str) -> str."""
    from ..llm.provider import LLMRequest, LLMResponse

    async def _complete(prompt: str) -> str:
        req = LLMRequest(prompt=prompt, temperature=0.7, max_tokens=2048)
        resp: LLMResponse = await llm.generate(req)
        return resp.content

    return _complete


def init_capabilities(settings: Settings) -> dict[str, Any]:
    """Initialise core AI capabilities (LLM, sandbox, memory, ontology, evolution)."""
    from ..council.orchestrator import CouncilOrchestrator
    from ..evolution.dgm import DGMEngine
    from ..llm.dynamic_router import DynamicModelRouter
    from ..llm.manager import LLMManager
    from ..llm.state_manager import get_llm_state_manager
    from ..metacognition.metacognition import MetacognitionService
    from ..ontology.engine import OntologyEngine
    from ..sandbox.secure_sandbox import SandboxConfig, SecurityLevel, create_secure_sandbox
    from ..tools.registry import ToolRegistry

    llm = LLMManager(
        settings.providers,
        settings.fallback_chain,
        state_manager=get_llm_state_manager(),
    )
    task_model_router = DynamicModelRouter(llm)
    council_orchestrator = CouncilOrchestrator(
        complete_fn=_make_council_complete_fn(llm),
    )

    # R-10：沙箱级别可配置。BASIC = AST 危险操作拦截 + 全 argv 命令检查；
    # STRICT 额外强制导入白名单、并施加进程数上限。默认 basic 以兼容代码生成回路。
    import os as _os

    _level_name = (_os.getenv("MORE_SANDBOX_LEVEL", "basic") or "basic").strip().lower()
    try:
        _level = SecurityLevel(_level_name)
    except ValueError:
        _level = SecurityLevel.BASIC
    sandbox = create_secure_sandbox(
        SandboxConfig(
            timeout_s=settings.sandbox_timeout_s,
            memory_mb=settings.sandbox_memory_mb,
            security_level=_level,
        ),
    )

    memory = _create_memory(settings)
    ontology = OntologyEngine()
    metacognition = MetacognitionService()
    evolution_archive = _create_evolution_archive(settings)
    evolution = DGMEngine(evolution_archive)
    tools = ToolRegistry()

    # ── v3.0 Meta-Orchestrator + Dynamic Guardrails ──────────────────────
    from ..v3.meta_orchestrator import MetaOrchestrator
    from ..v3.dynamic_guardrails import get_dynamic_guardrails

    meta_orchestrator = MetaOrchestrator(
        layer_router=None,  # Wired later in orchestrator post-bootstrap
        memory=memory,
    )
    dynamic_guardrails = get_dynamic_guardrails()

    return {
        "llm": llm,
        "task_model_router": task_model_router,
        "council_orchestrator": council_orchestrator,
        "sandbox": sandbox,
        "memory": memory,
        "ontology": ontology,
        "metacognition": metacognition,
        "evolution_archive": evolution_archive,
        "evolution": evolution,
        "tools": tools,
        "meta_orchestrator": meta_orchestrator,
        "dynamic_guardrails": dynamic_guardrails,
    }


def init_layers(settings: Settings) -> dict[str, Any]:
    """Initialise the L0–L5 layer pipeline and routing."""
    from ..core.types import LayerId
    from ..governance.audit import AuditLogger
    from ..governance.policy import PolicyEnforcer
    from ..layers.l0_execution import ExecutionLayer
    from ..layers.l1_orchestration import OrchestrationLayer
    from ..layers.l2_evolution import EvolutionLayer
    from ..layers.l3_symbolic import SymbolicLayer
    from ..layers.l4_cognition import CognitionLayer
    from ..layers.l5_metacognition import MetacognitionLayer
    from ..router.layer_router import LayerRouter

    router = LayerRouter(settings)
    layers = {
        LayerId.L0: ExecutionLayer(),
        LayerId.L1: OrchestrationLayer(),
        LayerId.L2: EvolutionLayer(),
        LayerId.L3: SymbolicLayer(),
        LayerId.L4: CognitionLayer(),
        LayerId.L5: MetacognitionLayer(),
    }
    audit = AuditLogger(settings.audit_log_path)
    policy = PolicyEnforcer(settings)

    return {
        "router": router,
        "layers": layers,
        "audit": audit,
        "policy": policy,
    }


def init_services(settings: Settings) -> dict[str, Any]:
    """Initialise service-layer subsystems (channels, cron, skills, hands, security, planning, workflows)."""
    import os as _os

    from ..channels.manager import ChannelManager
    from ..commands.registry import CommandRegistry
    from ..cron.scheduler import CronScheduler
    from ..deploy.manager import DeploymentManager
    from ..hands.manager import HandManager
    from ..hands.persistence import HandCloner, HandPersistence
    from ..hands.registry import HandRegistry
    from ..optimization import CacheConfig, CircuitBreaker, RateLimiter, RequestCache
    from ..planning.coordinator import PlanCoordinator
    from ..planning.plan_monitor import PlanMonitor
    from ..planning.token_predictor import TokenPredictor
    from ..planning.workflow_bridge import PlanWorkflowBridge
    from ..plugins.manager import PluginManager
    from ..channels.reconnect import ReconnectManager
    from ..security.output_filter import OutputFilter
    from ..security.rbac import UnifiedRBAC, set_rbac_instance
    from ..security.taint import TaintTracker
    from .sessions import SessionManager
    from ..skills import create_default_skill_manager
    from ..workflows.engine import WorkflowEngine

    _admin_raw = _os.environ.get("MORE_ADMIN_USERS", "")
    _admin_users = _admin_raw.split(",") if _admin_raw else None

    rbac = UnifiedRBAC(admin_users=_admin_users)
    set_rbac_instance(rbac)

    # Shared singletons reused across the graph
    _cron = CronScheduler()
    _hand_registry = HandRegistry()
    _hands = HandManager(_hand_registry, _cron)
    _token_predictor = TokenPredictor()
    _workflows = WorkflowEngine()

    return {
        "channels": ChannelManager(),
        "cron": _cron,
        "skill_manager": create_default_skill_manager(),
        "hand_registry": _hand_registry,
        "hands": _hands,
        "commands": CommandRegistry(),
        "plugins": PluginManager(settings.plugin_dir),
        "rbac": rbac,
        "taint_tracker": TaintTracker(),
        "output_filter": OutputFilter(),
        "reconnect_manager": ReconnectManager(),
        "hand_persistence": HandPersistence(),
        "hand_cloner": HandCloner(_hands),
        "planner": PlanCoordinator(),
        "token_predictor": _token_predictor,
        "workflows": _workflows,
        "plan_bridge": PlanWorkflowBridge(_workflows, _token_predictor),
        "plan_monitor": PlanMonitor(),
        "deployment_manager": DeploymentManager(),
        "session_manager": SessionManager(),
        "rate_limiter": RateLimiter(
            rate=settings.rate_limit_rps,
            burst=settings.rate_limit_burst,
        ),
        "request_cache": RequestCache(
            CacheConfig(
                max_size=settings.cache_max_size,
                ttl_seconds=settings.cache_ttl_seconds,
            ),
        ),
        "llm_circuit_breaker": CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
        ),
    }


# ---------------------------------------------------------------------------
# Private helpers (shared with orchestrator)
# ---------------------------------------------------------------------------


def _create_memory(settings: Settings) -> object:
    import os as _os
    from ..memory.store import MemoryStore

    db = _os.getenv("MORE_MEMORY_DB")
    if db:
        from ..memory.sqlite_store import SQLiteMemoryStore

        return SQLiteMemoryStore(db)
    return MemoryStore()


def _create_evolution_archive(settings: Settings) -> EvolutionArchive:
    from ..evolution.archive import EvolutionArchive

    db = os.getenv("MORE_EVOLUTION_DB")
    if db:
        from ..evolution.sqlite_archive import SQLiteEvolutionArchive

        return SQLiteEvolutionArchive(db)
    return EvolutionArchive()
