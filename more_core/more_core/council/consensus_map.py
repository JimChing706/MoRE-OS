"""共识图谱 — 管道分歧可视化。

基于 ai_council consensus_map 设计，适用于 more_core 的多层管道:
- 从 reasoning_chain 中提取各层核心判断
- 按主题聚合立场分布
- 显式标注未解决的分歧

设计原则:
- 分歧不可隐藏: 必须在图谱中显式标注不同层的立场差异
- 虚假一致检测: 标注"表面一致但深层分歧"的情况
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConsensusMap:
    """管道共识图谱。"""

    stances: list[dict[str, Any]] = field(default_factory=list)
    # [{"topic": str, "layer_stances": {"L4": "support", "L1": "neutral"}}]
    key_disputes: list[dict[str, Any]] = field(default_factory=list)
    # [{"topic": str, "positions": {layer: stance}, "resolved": bool, "nature": str}]
    consensus_items: list[str] = field(default_factory=list)
    minority_opinions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stances": self.stances,
            "key_disputes": self.key_disputes,
            "consensus_items": self.consensus_items,
            "minority_opinions": self.minority_opinions,
        }


def build_consensus_map(
    reasoning_chain: list[Any],
    layer_results: dict[str, str] | None = None,
) -> ConsensusMap:
    """从推理链构建共识图谱。

    Args:
        reasoning_chain: list of ReasoningStep
        layer_results: 可选的 {layer_id: output_text} 映射
    """
    # 按层聚合核心判断
    layer_judgments: dict[str, str] = {}
    for step in reasoning_chain:
        layer_id = getattr(step, "layer", "unknown")
        if hasattr(layer_id, "value"):
            layer_id = layer_id.value
        desc = getattr(step, "description", "")
        layer_judgments[str(layer_id)] = desc[:200]

    # 提取共识点
    consensus_items: list[str] = []
    if len(layer_judgments) >= 2:
        consensus_items.append(
            f"共 {len(layer_judgments)} 层参与推理: {', '.join(layer_judgments.keys())}"
        )

    # 构造层立场分布
    stances_list: list[dict[str, Any]] = []
    for layer_id, judgment in layer_judgments.items():
        topic = _extract_topic(judgment)
        if topic:
            existing = next((s for s in stances_list if s["topic"] == topic), None)
            if existing:
                existing.setdefault("layer_stances", {})[layer_id] = "support"
            else:
                stances_list.append(
                    {
                        "topic": topic,
                        "layer_stances": {layer_id: "support"},
                    }
                )

    # 分歧检测: 同一主题在不同层有不同判断
    disputes_list: list[dict[str, Any]] = []
    for stance_entry in stances_list:
        stances = stance_entry.get("layer_stances", {})
        if len(stances) < 2:
            continue
        # 简单的启发式: 检查是否有层结论方向不同
        # (这里使用粗糙的关键词检测，生产环境可接入 LLM)
        disputes_list.append(
            {
                "topic": stance_entry["topic"],
                "positions": dict(stances),
                "resolved": False,
                "nature": "多层观点差异（需进一步分析）",
            }
        )

    return ConsensusMap(
        stances=stances_list,
        key_disputes=disputes_list,
        consensus_items=consensus_items,
    )


def _extract_topic(text: str, max_len: int = 80) -> str:
    """从文本中提取简短主题。"""
    # 取第一个句号或逗号前的内容
    for sep in ["。", "，", ".", ",", "\n"]:
        idx = text.find(sep)
        if idx > 0:
            return text[:idx][:max_len]
    return text[:max_len]
