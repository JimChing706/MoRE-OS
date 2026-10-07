"""Layer base class and per-layer execution context."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.types import LayerId, ReasoningStep, TaskRequest

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime.orchestrator import MoRECore


@dataclass(slots=True)
class LayerContext:
    """Shared per-task state that layers mutate."""

    core: MoRECore
    request: TaskRequest
    user_id: str = "anonymous"
    accumulated_steps: list[ReasoningStep] = field(default_factory=list)
    scratch: dict[str, Any] = field(default_factory=dict)
    step_counter: int = 0


@dataclass(slots=True)
class LayerResult:
    layer: LayerId
    description: str
    output: Any
    confidence: float = 0.8
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0.0


class Layer(ABC):
    """Concrete layers implement :meth:`process`."""

    layer_id: LayerId

    def __init__(self) -> None:
        pass

    @abstractmethod
    async def process(self, ctx: LayerContext) -> LayerResult: ...

    async def run(self, ctx: LayerContext) -> LayerResult:
        start = time.perf_counter()
        result = await self.process(ctx)
        result.duration_ms = (time.perf_counter() - start) * 1000
        ctx.step_counter += 1
        ctx.accumulated_steps.append(
            ReasoningStep(
                id=ctx.step_counter,
                layer=result.layer,
                description=result.description,
                duration_ms=result.duration_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                confidence=result.confidence,
            )
        )
        return result
