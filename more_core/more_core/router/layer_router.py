"""Difficulty-aware layer router.

Produces an ordered *pipeline* of layers to execute.  By default L4 → L3
(if enabled) → L1 → L0.  Self-improving tasks prepend L5/L2 when their
gates are open.

Pipeline templates are configurable: ``Settings.custom_pipelines`` can
override defaults, and plugins can call
:meth:`LayerRouter.register_pipeline` at activation time.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import Settings
from ..core.errors import RoutingError
from ..core.types import LayerId, TaskRequest, TaskType


@dataclass(slots=True)
class RoutingDecision:
    pipeline: list[LayerId]
    reasoning: str


DEFAULT_PIPELINES: dict[TaskType, list[LayerId]] = {
    TaskType.SELF_IMPROVEMENT: [LayerId.L5, LayerId.L2, LayerId.L1, LayerId.L0],
    TaskType.CROSS_DOMAIN_TRANSFER: [LayerId.L5, LayerId.L4, LayerId.L1, LayerId.L0],
    TaskType.MATH_REASONING: [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0],
    TaskType.MULTI_AGENT_ORCHESTRATION: [LayerId.L4, LayerId.L1, LayerId.L0],
    TaskType.CODE_GENERATION: [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0],
    TaskType.CODE_DEBUGGING: [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0],
    TaskType.CODE_REVIEW: [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0],
    TaskType.DATA_ANALYSIS: [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0],
    TaskType.NLP_TASK: [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0],
    TaskType.ARCHITECTURE_DESIGN: [LayerId.L5, LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0],
    TaskType.PLUGIN_DEFINED: [LayerId.L4, LayerId.L1, LayerId.L0],
}


class LayerRouter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Start from built-in defaults, then overlay any Settings overrides.
        self._pipelines: dict[TaskType, list[LayerId]] = dict(DEFAULT_PIPELINES)
        for type_name, layers in (settings.custom_pipelines or {}).items():
            tt = TaskType(type_name)
            self._pipelines[tt] = [LayerId(lid) for lid in layers]

    # -- plugin extension API -----------------------------------------------

    def register_pipeline(self, task_type: TaskType, pipeline: list[LayerId]) -> None:
        """Register or override a pipeline template (plugin hook)."""
        if LayerId.L0 not in pipeline:
            raise RoutingError("pipeline must contain L0")
        self._pipelines[task_type] = list(pipeline)

    def unregister_pipeline(self, task_type: TaskType) -> None:
        """Revert a task type to the built-in default (or remove if none)."""
        if task_type in DEFAULT_PIPELINES:
            self._pipelines[task_type] = list(DEFAULT_PIPELINES[task_type])
        else:
            self._pipelines.pop(task_type, None)

    def list_pipelines(self) -> dict[str, list[str]]:
        """Return current pipeline map (for introspection / API)."""
        return {
            tt.value: [lid.value for lid in layers]
            for tt, layers in self._pipelines.items()
        }

    # -- core routing -------------------------------------------------------

    def route(self, request: TaskRequest) -> RoutingDecision:
        if request.target_layer is not None:
            # Respect explicit routing: run L4 → target → L0 transitively.
            idx = int(request.target_layer.value[1])
            pipeline = [LayerId(f"L{i}") for i in range(5, -1, -1) if i <= idx]
            pipeline.reverse()
            if LayerId.L4 not in pipeline:
                pipeline.insert(0, LayerId.L4)
            return RoutingDecision(pipeline=pipeline, reasoning="explicit target_layer")

        pipeline = list(self._pipelines.get(request.type, self._pipelines[TaskType.NLP_TASK]))

        if request.require_metacognitive_monitoring and LayerId.L5 not in pipeline:
            pipeline.insert(0, LayerId.L5)

        # Enforce feature gates.
        if LayerId.L3 in pipeline and not self._settings.enable_symbolic:
            pipeline.remove(LayerId.L3)
        if LayerId.L2 in pipeline and not self._settings.enable_evolution:
            pipeline.remove(LayerId.L2)
        if LayerId.L5 in pipeline and not self._settings.enable_metacognition:
            # Calibration-only mode is allowed even when full metacog is off;
            # retain L5 if caller explicitly requested monitoring.
            if not request.require_metacognitive_monitoring:
                pipeline.remove(LayerId.L5)

        if LayerId.L0 not in pipeline:
            raise RoutingError("pipeline must end with L0")

        return RoutingDecision(
            pipeline=pipeline,
            reasoning=f"type={request.type.value} gates={self._gates_str()}",
        )

    def _gates_str(self) -> str:
        s = self._settings
        return (
            f"sym={int(s.enable_symbolic)} "
            f"evo={int(s.enable_evolution)} "
            f"meta={int(s.enable_metacognition)}"
        )
