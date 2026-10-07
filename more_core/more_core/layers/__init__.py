"""Layer abstractions L0–L5 with baseline implementations.

Each layer is a :class:`Layer` with a single ``process`` coroutine.  The
orchestrator composes selected layers into a pipeline per task; plugins
may register *replacement* layers implementing the same ``Protocol``.
"""

from .base import Layer, LayerContext, LayerResult
from .l0_execution import ExecutionLayer
from .l1_orchestration import OrchestrationLayer
from .l2_evolution import EvolutionLayer
from .l3_symbolic import SymbolicLayer
from .l4_cognition import CognitionLayer
from .l5_metacognition import MetacognitionLayer

__all__ = [
    "CognitionLayer",
    "EvolutionLayer",
    "ExecutionLayer",
    "Layer",
    "LayerContext",
    "LayerResult",
    "MetacognitionLayer",
    "OrchestrationLayer",
    "SymbolicLayer",
]
