"""管道输出质量自检 — 借鉴 ai_council chair_self_check。

在 more_core 管道执行完成后，对 LayerResult 的质量进行自我审计:
- 覆盖度检查: 每个推理步骤的核心论点是否被最终结论充分体现？
- 偏见检测: 是否存在某些层的输出被系统性忽略或弱化？
- 少数派保护: 回补被遗漏的重要观点。

设计原则:
- 自检在管道完成后运行，不影响主流程
- 自检结果记录到 TaskResult.metadata 中，可审计
- 发现严重遗漏时提供 backfill 建议
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.types import TaskType

_CODE_TASK_TYPES = frozenset(
    {
        TaskType.CODE_GENERATION,
        TaskType.CODE_DEBUGGING,
        TaskType.CODE_TESTING,
        TaskType.CODE_REVIEW,
    }
)


@dataclass
class SelfCheckReport:
    """管道输出自检报告。"""

    completeness_check: list[dict[str, Any]] = field(default_factory=list)
    # [{"layer": str, "core_output": str, "covered_in_final": bool, "note": str}]
    bias_check: list[dict[str, Any]] = field(default_factory=list)
    # [{"issue": str, "severity": "high"|"medium"|"low", "detail": str}]
    backfill_required: bool = False
    backfill_items: list[str] = field(default_factory=list)
    overall_assessment: str = ""
    coverage_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "completeness_check": self.completeness_check,
            "bias_check": self.bias_check,
            "backfill_required": self.backfill_required,
            "backfill_items": self.backfill_items,
            "overall_assessment": self.overall_assessment,
            "coverage_pct": round(self.coverage_pct, 1),
        }


def run_pipeline_self_check(
    reasoning_chain: list[Any],  # list of ReasoningStep
    final_output: str,
    task_type: TaskType | None = None,
) -> SelfCheckReport:
    """对管道输出执行启发式自检。

    检查策略:
    1. 每层推理步骤的关键词是否在最终输出中出现
    2. 是否存在明显被忽略的层输出
    3. 计算覆盖度百分比

    代码任务走专用分支：最终输出中出现可执行代码产物即视为覆盖完整，
    关键词覆盖启发式对代码输出无意义（代码中不会出现“策略=balanced”这类
    层描述词，旧逻辑会让每个代码任务固定报 0% 覆盖）。
    """
    if task_type in _CODE_TASK_TYPES:
        return _self_check_code(reasoning_chain, str(final_output))
    return _self_check_text(reasoning_chain, str(final_output))


def _self_check_code(reasoning_chain: list[Any], final_output: str) -> SelfCheckReport:
    """Code-task self-check: success = an executable code artifact is delivered."""
    has_code = _contains_code_artifact(final_output)
    completeness: list[dict[str, Any]] = []
    for step in reasoning_chain:
        layer_id = getattr(step, "layer", "unknown")
        if hasattr(layer_id, "value"):
            layer_id = layer_id.value
        desc = getattr(step, "description", "")
        completeness.append(
            {
                "layer": str(layer_id),
                "core_output": desc[:120],
                "covered_in_final": has_code,
                "note": "代码产物已生成" if has_code else "最终输出中未检测到可执行代码",
            }
        )
    return SelfCheckReport(
        completeness_check=completeness,
        backfill_required=not has_code,
        backfill_items=(
            ["未生成代码产物（无 ```python 代码块或可编译源码）"] if not has_code else []
        ),
        overall_assessment=("代码产物完整" if has_code else "代码任务未产出代码: 需人工介入"),
        coverage_pct=100.0 if has_code else 0.0,
    )


def _contains_code_artifact(text: str) -> bool:
    """True when *text* carries a fenced code block or bare compilable code."""
    if not text:
        return False
    lower = text.lower()
    if "```python" in lower or "```py" in lower:
        return True
    if not _looks_like_python(text):
        return False
    try:
        compile(text, "<self-check>", "exec")
    except (SyntaxError, ValueError, TypeError):
        return False
    return True


def _looks_like_python(text: str) -> bool:
    lower = text.lower()
    return any(
        token in lower
        for token in ("def ", "class ", "import ", "from ", "print(", "print (", "return ")
    )


def _self_check_text(reasoning_chain: list[Any], final_output: str) -> SelfCheckReport:
    """Text-task self-check: keyword-coverage heuristic over reasoning steps."""
    completeness: list[dict[str, Any]] = []
    covered_count = 0
    total_steps = len(reasoning_chain)

    for step in reasoning_chain:
        layer_id = getattr(step, "layer", "unknown")
        desc = getattr(step, "description", "")
        if hasattr(layer_id, "value"):
            layer_id = layer_id.value

        # 检查 description 的关键词是否在 final_output 中出现
        keywords = _extract_keywords(desc)
        covered = any(kw.lower() in final_output.lower() for kw in keywords if len(kw) > 2)

        completeness.append(
            {
                "layer": str(layer_id),
                "core_output": desc[:120],
                "covered_in_final": covered,
                "note": "关键词覆盖" if covered else "未在最终输出中直接体现",
            }
        )
        if covered:
            covered_count += 1

    coverage_pct = (covered_count / total_steps * 100) if total_steps > 0 else 100.0

    # 偏见检测: 检查是否某些层输出被系统性忽略
    bias_items: list[dict[str, Any]] = []
    layer_coverages: dict[str, tuple[int, int]] = {}
    for item in completeness:
        layer = str(item["layer"])
        prev = layer_coverages.get(layer, (0, 0))
        layer_coverages[layer] = (prev[0] + (1 if item["covered_in_final"] else 0), prev[1] + 1)

    for layer, (cov, total) in layer_coverages.items():
        layer_pct = (cov / total * 100) if total > 0 else 100.0
        if layer_pct < 50 and total >= 2:
            bias_items.append(
                {
                    "issue": f"{layer} 层输出在最终结论中覆盖率仅 {layer_pct:.0f}%",
                    "severity": "medium" if layer_pct < 30 else "low",
                    "detail": f"该层 {total} 个推理步骤中仅 {covered} 个被覆盖",
                }
            )

    # 回补判断
    backfill_items: list[str] = []
    for item in completeness:
        if not item["covered_in_final"]:
            backfill_items.append(f"[{item['layer']}] {item['core_output'][:80]}")

    needs_backfill = coverage_pct < 60.0

    return SelfCheckReport(
        completeness_check=completeness,
        bias_check=bias_items,
        backfill_required=needs_backfill,
        backfill_items=backfill_items[:5] if backfill_items else [],
        overall_assessment=(
            f"覆盖度 {coverage_pct:.0f}%: "
            f"{'良好' if coverage_pct >= 80 else '一般' if coverage_pct >= 60 else '需改进'}"
        ),
        coverage_pct=coverage_pct,
    )


def _extract_keywords(text: str, max_keywords: int = 5) -> list[str]:
    """从文本中提取关键词（简单分词）。"""
    # 中英文混合分词
    words = text.replace(",", " ").replace(".", " ").replace("，", " ").replace("。", " ").split()
    # 去重，取前 N 个
    seen = set()
    result = []
    for w in words:
        lower = w.lower()
        if lower not in seen and len(w) > 1:
            seen.add(lower)
            result.append(w)
            if len(result) >= max_keywords:
                break
    return result
