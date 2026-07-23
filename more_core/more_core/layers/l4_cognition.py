"""L4 — Cognition Layer (task parsing, planning, difficulty estimation).

Includes LLM-based task decomposition for complex queries.
"""

from __future__ import annotations

import json
import logging
import re

from typing import Any

from ..core.types import LayerId, TaskType
from ..core.unicode_utils import semantic_length
from ..llm.provider import LLMRequest
from .base import Layer, LayerContext, LayerResult

_log = logging.getLogger(__name__)


_DIFFICULTY_BASE: dict[TaskType, int] = {
    TaskType.NLP_TASK: 3,
    TaskType.CODE_GENERATION: 5,
    TaskType.CODE_DEBUGGING: 6,
    TaskType.CODE_REVIEW: 5,
    TaskType.CODE_TESTING: 6,
    TaskType.MATH_REASONING: 7,
    TaskType.DATA_ANALYSIS: 5,
    TaskType.MULTI_AGENT_ORCHESTRATION: 6,
    TaskType.SELF_IMPROVEMENT: 9,
    TaskType.CROSS_DOMAIN_TRANSFER: 9,
    TaskType.ARCHITECTURE_DESIGN: 8,
    TaskType.PLUGIN_DEFINED: 5,
}

_DECOMPOSE_THRESHOLD = (
    6  # Lowered from 7: "optimize logistics with DP" difficulty=6 now triggers decomposition
)

# Signals that increase estimated difficulty
_COMPLEXITY_KEYWORDS = {
    "en": [
        "integrate",
        "distributed",
        "concurrent",
        "optimize",
        "architecture",
        "migration",
        "refactor",
        "security",
        "scalable",
        "multi-",
    ],
    "zh": ["集成", "分布式", "并发", "优化", "架构", "迁移", "重构", "安全", "可扩展", "多模块"],
}

# Code-specific complexity signals — these indicate the task requires
# multi-file or multi-component code generation.
_CODE_COMPLEXITY_KEYWORDS = {
    "en": [
        "full-stack",
        "crud",
        "rest api",
        "database",
        "authentication",
        "authorization",
        "pipeline",
        "deploy",
        "docker",
        "frontend",
        "backend",
        "endpoint",
        "middleware",
        "migration",
        "schema",
        "full stack",
        "microservice",
        "websocket",
        "queue",
        "cache",
    ],
    "zh": [
        "全栈",
        "增删改查",
        "接口",
        "数据库",
        "认证",
        "授权",
        "管道",
        "部署",
        "前端",
        "后端",
        "中间件",
        "数据模型",
        "微服务",
        "缓存",
        "消息队列",
    ],
}

_CODE_TASK_TYPES_L4 = frozenset(
    {
        TaskType.CODE_GENERATION,
        TaskType.CODE_DEBUGGING,
        TaskType.CODE_TESTING,
        TaskType.CODE_REVIEW,
    }
)


def _estimate_complexity_bonus(query: str) -> int:
    """Award bonus difficulty points based on semantic complexity signals."""
    bonus = 0
    lower = query.lower()
    for kw in _COMPLEXITY_KEYWORDS["en"]:
        if kw in lower:
            bonus += 1
    for kw in _COMPLEXITY_KEYWORDS["zh"]:
        if kw in query:
            bonus += 1
    # Code-specific complexity keywords add extra weight
    for kw in _CODE_COMPLEXITY_KEYWORDS["en"]:
        if kw in lower:
            bonus += 1
    for kw in _CODE_COMPLEXITY_KEYWORDS["zh"]:
        if kw in query:
            bonus += 1
    return min(4, bonus)  # cap bonus at 4 (raised from 3 for code tasks)


class CognitionLayer(Layer):
    layer_id = LayerId.L4

    async def process(self, ctx: LayerContext) -> LayerResult:
        difficulty = _DIFFICULTY_BASE.get(ctx.request.type, 5)
        # Longer queries trend more complex; cap at 10.
        # Use semantic_length for CJK-aware estimation (Chinese char ≈ 2 English chars).
        difficulty = min(10, difficulty + min(3, semantic_length(ctx.request.query) // 400))
        # Context-aware complexity bonus
        difficulty = min(10, difficulty + _estimate_complexity_bonus(ctx.request.query))

        # Estimate system capability based on available resources
        capability = 7
        if ctx.core.llm and ctx.core.llm.list_providers():
            capability = min(10, 6 + len(ctx.core.llm.list_providers()))
        ctx.scratch["capability"] = capability

        if difficulty >= _DECOMPOSE_THRESHOLD and ctx.core.llm:
            plan = await self._decompose_with_llm(ctx, difficulty)
        else:
            plan = {
                "subtasks": [ctx.request.query],
                "difficulty": difficulty,
                "decomposed": False,
            }

        ctx.scratch["difficulty"] = difficulty

        # Bridge L4 decomposition → PlanCoordinator for rigorous execution tracking.
        # When the task was decomposed by LLM, feed subtasks directly into the
        # PlanCoordinator so L5 monitoring and budget tracking apply automatically.
        if plan.get("decomposed") and len(plan.get("subtasks", [])) > 1:
            if hasattr(ctx.core, "planner") and ctx.core.planner is not None:
                exec_plan = ctx.core.planner.create_plan(
                    goal=ctx.request.query,
                    subtasks=plan["subtasks"],
                    difficulty=difficulty,
                )
                issues = ctx.core.planner.validate_plan(exec_plan)
                if not issues:
                    plan["plan_id"] = exec_plan.id
                else:
                    _log.warning("Plan validation issues for %s: %s", exec_plan.id, issues)

        ctx.scratch["plan"] = plan

        # Generate structured plan for L5 monitoring (DeepSeek TUI pattern)
        from ..planning.structured_plan import merge_plan_with_l4_output

        structured = merge_plan_with_l4_output(plan, ctx.request.query)
        if structured:
            structured.start_next_phase()  # activate first phase
            ctx.scratch["structured_plan"] = structured.to_dict()
            ctx.scratch["_structured_plan_obj"] = structured

        confidence = 0.88 if not plan.get("decomposed") else 0.92

        return LayerResult(
            layer=self.layer_id,
            description=f"parsed task, difficulty={difficulty}, capability={capability}, subtasks={len(plan.get('subtasks', []))}",
            output=plan,
            confidence=confidence,
        )

    async def _decompose_with_llm(self, ctx: LayerContext, base_difficulty: int) -> dict[str, Any]:
        """Use LLM to decompose complex tasks into subtasks."""
        try:
            prompt = self._build_decompose_prompt(ctx)
            llm_req = LLMRequest(
                prompt=prompt,
                system="You are a task planning system. Decompose complex tasks into simpler subtasks.",
                temperature=0.5,
                max_tokens=1024,
            )

            resp = await ctx.core.llm.generate(llm_req)
            subtasks = self._parse_subtasks(resp.content)

            # Sanitize LLM-generated subtasks before storing in scratch
            # This prevents L4→L0 injection chains
            if subtasks and hasattr(ctx.core, "output_filter"):
                subtasks = [ctx.core.output_filter.filter(st) for st in subtasks]

            if subtasks and len(subtasks) > 1:
                adjusted_difficulty = min(10, base_difficulty + len(subtasks) // 2)
                return {
                    "subtasks": subtasks,
                    "difficulty": adjusted_difficulty,
                    "decomposed": True,
                    "decomposition_method": "llm",
                }

        except Exception as exc:
            _log.warning("L4 LLM decomposition failed for task %s: %s", ctx.request.id, exc)

        return {
            "subtasks": [ctx.request.query],
            "difficulty": base_difficulty,
            "decomposed": False,
        }

    def _build_decompose_prompt(self, ctx: LayerContext) -> str:
        from ..core.unicode_utils import is_predominantly_cjk

        is_code = ctx.request.type in _CODE_TASK_TYPES_L4

        if is_predominantly_cjk(ctx.request.query):
            if is_code:
                return f"""将以下代码任务分解为 2-5 个独立的实现子任务。

任务类型: {ctx.request.type.value}
查询内容: {ctx.request.query}

代码任务分解指南 — 将需求拆分为:
- 数据模型/类型定义
- 核心函数/类实现
- API 端点/接口层
- 错误处理/边界情况
- 测试/验证

以 JSON 字符串数组格式输出子任务:
```json
["子任务1描述", "子任务2描述", ...]
```

每个子任务应满足:
- 具体性（指明要实现的具体函数/类/模块）
- 可操作性（可以直接生成对应代码）
- 顺序无关（可独立实现）

仅在 <subtasks> 标签中输出有效的 JSON:"""
            return f"""将以下任务分解为 2-5 个独立的子任务。

任务类型: {ctx.request.type.value}
查询内容: {ctx.request.query}

以 JSON 字符串数组格式输出子任务:
```json
["子任务1描述", "子任务2描述", ...]
```

每个子任务应满足:
- 独立性（可以任意顺序执行）
- 具体性（有明确的输入和预期输出）
- 可操作性（指明具体操作）

仅在 <subtags> 标签中输出有效的 JSON:"""

        if is_code:
            return f"""Decompose the following code task into 2-5 independent implementation subtasks.

Task Type: {ctx.request.type.value}
Query: {ctx.request.query}

Code task decomposition guide — break requirements into:
- Data model / type definitions
- Core functions / class implementations
- API endpoints / interface layer
- Error handling / edge cases
- Tests / validation

Output the subtasks as a JSON array of strings:
```json
["subtask 1 description", "subtask 2 description", ...]
```

Each subtask should be:
- Specific (name the function/class/module to implement)
- Actionable (code can be generated directly from the description)
- Independent (can be implemented in any order)

Output ONLY valid JSON in <subtasks> tags:"""

        return f"""Decompose the following task into 2-5 independent subtasks.

Task Type: {ctx.request.type.value}
Query: {ctx.request.query}

Output the subtasks as a JSON array of strings:
```json
["subtask 1 description", "subtask 2 description", ...]
```

Each subtask should be:
- Independent (can be executed in any order)
- Specific (clear input and expected output)
- Actionable (specifies what to do)

Output ONLY valid JSON in <subtasks> tags:"""

    def _parse_subtasks(self, content: str) -> list[str]:
        match = re.search(r"<subtasks>\s*(\[[\s\S]*?\])\s*</subtasks>", content)
        if not match:
            match = re.search(r"```json\s*(\[[\s\S]*?\])\s*```", content)

        if not match:
            return []

        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
                return parsed
        except json.JSONDecodeError:
            pass

        return []
