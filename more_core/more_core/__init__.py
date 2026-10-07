"""QNMing MoRE OS — Neuro-Symbolic Metacognitive Self-Evolving Agent OS Kernel.

Layered architecture (L0–L5) providing domain-neutral execution, orchestration,
evolution, symbolic reasoning, cognition, and metacognition capabilities.
See ARCHITECTURE.md for details.

Product: QNMing MoRE OS  |  License: Apache-2.0
"""

from .core.errors import (
    GovernanceError,
    LLMError,
    MoREError,
    PluginError,
    RoutingError,
    SandboxError,
)
from .core.types import (
    LayerId,
    PerformanceMetrics,
    ReasoningStep,
    TaskRequest,
    TaskResult,
    TaskStatus,
    TaskType,
)
from .core.unicode_utils import (
    detect_language,
    is_cjk_char,
    is_predominantly_cjk,
    normalize_for_search,
    semantic_length,
)
from .runtime.orchestrator import MoRECore
from .version import __author__, __product__, __version__

__all__ = [
    "GovernanceError",
    "LLMError",
    "LayerId",
    "MoRECore",
    "MoREError",
    "PerformanceMetrics",
    "PluginError",
    "ReasoningStep",
    "RoutingError",
    "SandboxError",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
    "TaskType",
    "__author__",
    "__product__",
    "__version__",
    "detect_language",
    "is_cjk_char",
    "is_predominantly_cjk",
    "normalize_for_search",
    "semantic_length",
]
