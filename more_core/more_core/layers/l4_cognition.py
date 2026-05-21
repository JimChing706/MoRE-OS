"""L4 — Cognition Layer (task parsing, planning, difficulty estimation).

Includes LLM-based task decomposition for complex queries.
"""

from __future__ import annotations

import json
import re

from ..core.types import LayerId, TaskType
from ..core.unicode_utils import semantic_length
from ..llm.provider import LLMRequest
from .base import Layer, LayerContext, LayerResult


_DIFFICULTY_BASE: dict[TaskType, int] = {
    TaskType.NLP_TASK: 3,
    TaskType.CODE_GENERATION: 5,
    TaskType.CODE_DEBUGGING: 6,
    TaskType.CODE_REVIEW: 5,
    TaskType.MATH_REASONING: 7,
    TaskType.DATA_ANALYSIS: 5,
    TaskType.MULTI_AGENT_ORCHESTRATION: 6,
    TaskType.SELF_IMPROVEMENT: 9,
    TaskType.CROSS_DOMAIN_TRANSFER: 9,
    TaskType.ARCHITECTURE_DESIGN: 8,
    TaskType.PLUGIN_DEFINED: 5,
}

_DECOMPOSE_THRESHOLD = 7

# Signals that increase estimated difficulty
_COMPLEXITY_KEYWORDS = {
    "en": ["integrate", "distributed", "concurrent", "optimize", "architecture",
           "migration", "refactor", "security", "scalab", "multi-"],
    "zh": ["集成", "分布式", "并发", "优化", "架构", "迁移", "重构", "安全", "可扩展", "多模块"],
}


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
    return min(3, bonus)  # cap bonus at 3


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
        if ctx.core.llm.list_providers():
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
        ctx.scratch["plan"] = plan
        
        confidence = 0.88 if not plan.get("decomposed") else 0.92
        
        return LayerResult(
            layer=self.layer_id,
            description=f"parsed task, difficulty={difficulty}, capability={capability}, subtasks={len(plan.get('subtasks', []))}",
            output=plan,
            confidence=confidence,
        )

    async def _decompose_with_llm(
        self, ctx: LayerContext, base_difficulty: int
    ) -> dict:
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

            if subtasks and len(subtasks) > 1:
                adjusted_difficulty = min(10, base_difficulty + len(subtasks) // 2)
                return {
                    "subtasks": subtasks,
                    "difficulty": adjusted_difficulty,
                    "decomposed": True,
                    "decomposition_method": "llm",
                }

        except Exception:
            pass

        return {
            "subtasks": [ctx.request.query],
            "difficulty": base_difficulty,
            "decomposed": False,
        }

    def _build_decompose_prompt(self, ctx: LayerContext) -> str:
        from ..core.unicode_utils import is_predominantly_cjk

        if is_predominantly_cjk(ctx.request.query):
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

仅在 <subtasks> 标签中输出有效的 JSON:"""

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
