"""QNMing MoRE OS — Neuro-Symbolic Metacognitive Self-Evolving Agent OS Kernel.

Layered architecture (L0–L5) providing domain-neutral execution, orchestration,
evolution, symbolic reasoning, cognition, and metacognition capabilities.
See ARCHITECTURE.md for details.

Product: QNMing MoRE OS  |  License: Apache-2.0
"""

from .version import __version__, __product__, __author__
from .core.types import (
    LayerId,
    TaskType,
    TaskStatus,
    TaskRequest,
    TaskResult,
    ReasoningStep,
    PerformanceMetrics,
)
from .core.errors import (
    MoREError,
    PluginError,
    LLMError,
    SandboxError,
    GovernanceError,
    RoutingError,
)
from .core.unicode_utils import (
    detect_language,
    semantic_length,
    is_cjk_char,
    is_predominantly_cjk,
    normalize_for_search,
)
from .runtime.orchestrator import MoRECore

__all__ = [
    "__version__",
    "__product__",
    "__author__",
    "LayerId",
    "TaskType",
    "TaskStatus",
    "TaskRequest",
    "TaskResult",
    "ReasoningStep",
    "PerformanceMetrics",
    "MoREError",
    "PluginError",
    "LLMError",
    "SandboxError",
    "GovernanceError",
    "RoutingError",
    "MoRECore",
    "detect_language",
    "semantic_length",
    "is_cjk_char",
    "is_predominantly_cjk",
    "normalize_for_search",
]
