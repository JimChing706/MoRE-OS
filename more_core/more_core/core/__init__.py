"""Core primitives: types, errors, configuration, registry, event bus, deliverable."""

from .config import LLMProviderConfig, Settings
from .convergence import (
    ConvergenceReport,
    ConvergenceSnapshot,
    ConvergenceState,
    ConvergenceTracker,
)
from .deliverable import (
    DeliverableContract,
    DeliverableKind,
    KillCriterion,
    KillSeverity,
    TaskExpectation,
)
from .errors import (
    GovernanceError,
    LLMError,
    MoREError,
    PluginError,
    RoutingError,
    SandboxError,
)
from .event_bus import Event, EventBus
from .service_registry import ServiceRegistry
from .types import (
    EngineStatus,
    LayerId,
    PerformanceMetrics,
    ReasoningStep,
    ServiceMetadata,
    TaskRequest,
    TaskResult,
    TaskStatus,
    TaskType,
)

__all__ = [
    "ConvergenceReport",
    "ConvergenceSnapshot",
    "ConvergenceState",
    "ConvergenceTracker",
    "DeliverableContract",
    "DeliverableKind",
    "EngineStatus",
    "Event",
    "EventBus",
    "GovernanceError",
    "KillCriterion",
    "KillSeverity",
    "LLMError",
    "LLMProviderConfig",
    "LayerId",
    "MoREError",
    "PerformanceMetrics",
    "PluginError",
    "ReasoningStep",
    "RoutingError",
    "SandboxError",
    "ServiceMetadata",
    "ServiceRegistry",
    "Settings",
    "TaskExpectation",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
    "TaskType",
]
