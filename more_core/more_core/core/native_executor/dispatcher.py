"""Single-point template dispatcher: Planner + Writer share the same template key.

Tasks 装配层唯一可信入口：一次调用 = (steps + payload_map + warnings + template_key)。
杜绝 tasks.py 各自 new Planner/Writer 发生 key 错位。
"""

from __future__ import annotations

from typing import Any, Optional

from .planner import TaskTemplateSelector
from .types import TaskTemplateKey, TemplateDispatchResult
from .writer import TaskPayloadTemplateRegistry


class TemplateDispatcher:
    """Planner + Writer 同一 key 单点分派器。"""

    @staticmethod
    def dispatch(
        task_request: Any,
        project_root: str,
        doc: Optional[str],
    ) -> TemplateDispatchResult:
        warnings: list[str] = []
        selector = TaskTemplateSelector()
        key: TaskTemplateKey = selector.key_for(task_request, doc)
        steps = selector.plan_for_key(key)

        registry = TaskPayloadTemplateRegistry()
        mixin = registry.get(key)
        payload_map = mixin.build_payload_map(task_request, doc, steps)

        if key == "generic":
            warnings.append(
                "using_generic_template: no cs_shooter/tetris matched; "
                "scaffold is minimal, expand manually or register new template"
            )

        return TemplateDispatchResult(
            key=key,
            plan_steps=steps,
            payload_map=payload_map,
            warnings=warnings,
        )
