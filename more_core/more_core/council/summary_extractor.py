"""分层摘要提取 — 借鉴 ai_council 2 summary_extractor (T18 上下文管理)。

为长上下文场景提供分层摘要能力:
- 将角色输出压缩为可控长度的摘要
- 保留关键论点，舍弃冗余细节
- 支持多级摘要（1 行 / 3 句 / 全量）

设计原则:
- 摘要过程可审计（记录取舍决策）
- 分层摘要供上下文管理使用（长会话自动压缩）
"""

from typing import Any


# 摘要层级
SUMMARY_LEVELS = ("one_line", "three_sentences", "compact", "full")


def summarize_role_output(output: dict[str, Any], level: str = "compact") -> str:
    """将单个角色输出压缩为指定层级的摘要。

    Args:
        output: 角色输出字典
        level: one_line / three_sentences / compact / full

    Returns:
        指定层级的摘要文本
    """
    if level == "full":
        return str(output)

    role = output.get("role", "unknown")
    core = output.get("core_judgment", "")
    concern = output.get("top_concern", "")
    suggestion = output.get("constructive_suggestion", "")

    if level == "one_line":
        return f"[{role}] {core[:120]}" if core else f"[{role}] (无核心判断)"

    if level == "three_sentences":
        parts = []
        if core:
            parts.append(f"[{role}] 核心判断: {core[:150]}")
        if concern:
            parts.append(f"  关注点: {concern[:100]}")
        if suggestion:
            parts.append(f"  建议: {suggestion[:100]}")
        return "\n".join(parts) if parts else f"[{role}] (无内容)"

    # compact
    key_args = output.get("key_arguments", [])
    lines = [f"=== {role} ==="]
    if core:
        lines.append(f"判断: {core[:200]}")
    for i, arg in enumerate(key_args[:3]):
        point = arg.get("point", "") if isinstance(arg, dict) else str(arg)
        lines.append(f"论点{i + 1}: {point[:150]}")
    if concern:
        lines.append(f"风险: {concern[:100]}")
    if suggestion:
        lines.append(f"建议: {suggestion[:100]}")
    return "\n".join(lines)


def summarize_outputs(
    outputs: list[dict[str, Any]],
    level: str = "compact",
    max_total_chars: int = 8000,
) -> str:
    """将多个角色输出压缩为分层摘要。

    Args:
        outputs: 角色输出列表
        level: 摘要层级
        max_total_chars: 最大总字符数（超过时自动升级压缩级别）

    Returns:
        汇总摘要文本
    """
    if not outputs:
        return "(无输出)"

    result_parts: list[str] = []
    total_chars = 0

    fallback_levels = {
        "compact": "three_sentences",
        "three_sentences": "one_line",
    }

    current_level = level
    for out in outputs:
        summary = summarize_role_output(out, current_level)
        # 如果超过限制，升级压缩级别
        if total_chars + len(summary) > max_total_chars and current_level in fallback_levels:
            current_level = fallback_levels[current_level]
            # 重新压缩已有和当前输出
            new_parts = [
                summarize_role_output(o, current_level) for o in outputs[: len(result_parts)]
            ]
            result_parts = new_parts
            total_chars = sum(len(p) for p in result_parts)
            summary = summarize_role_output(out, current_level)

        result_parts.append(summary)
        total_chars += len(summary)

    # 如果仍然超限，截断
    if total_chars > max_total_chars:
        return "\n\n---\n\n".join(result_parts)[:max_total_chars] + "\n...(截断)"

    return "\n\n---\n\n".join(result_parts)
