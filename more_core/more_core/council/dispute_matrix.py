"""争议矩阵 — 从交叉审查中提取角色间冲突表。

借鉴 ai_council 2 的 B3 dispute_matrix 设计模式。
适用场景: 多角色认知辩论后，可视化角色间的观点冲突。

设计原则:
- 从 directed_response 中提取 stance
- 构建 role × role 的冲突矩阵
- 标注每个冲突点的 resolution_status
"""

from typing import Any

from dataclasses import dataclass, field


@dataclass
class DisputeMatrix:
    """争议矩阵 — 角色间观点冲突的表格化表示。

    entries: 每项为一个角色对之间的冲突条目
    summary: 统计摘要(总冲突数/已解决/未解决)
    """

    entries: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"entries": self.entries, "summary": self.summary}

    @classmethod
    def from_outputs(cls, all_outputs: list[dict[str, Any]]) -> "DisputeMatrix":
        entries: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str, str]] = set()

        for out in all_outputs:
            role = out.get("role", "unknown")
            dr = out.get("directed_response")
            if not dr:
                continue

            target = dr.get("target_role", "")
            topic = dr.get("target_point", "")[:80]
            stance = dr.get("stance", "neutral")

            pair_key = (role, target, topic)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            entry = {
                "role_a": role,
                "role_b": target,
                "topic": topic,
                "stance_a": stance,
                "stance_b": "等待推断",
                "resolved": False,
            }
            entries.append(entry)

        # 推断 target 的立场(从 core_judgment 方向)
        role_judgments: dict[str, str] = {}
        for out in all_outputs:
            role_judgments[out.get("role", "")] = out.get("core_judgment", "")

        for entry in entries:
            target_judgment = role_judgments.get(entry["role_b"], "")
            if any(kw in target_judgment for kw in ["反对", "不行", "风险", "高估", "不支持"]):
                entry["stance_b"] = "oppose"
            elif any(kw in target_judgment for kw in ["支持", "可行", "机会", "推荐"]):
                entry["stance_b"] = "support"
            else:
                entry["stance_b"] = "neutral"

        total = len(entries)
        resolved = sum(1 for e in entries if e["resolved"])
        summary = {
            "total_conflicts": total,
            "resolved": resolved,
            "unresolved": total - resolved,
        }

        return cls(entries=entries, summary=summary)
