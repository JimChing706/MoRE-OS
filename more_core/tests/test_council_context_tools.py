"""Council 上下文工具测试：summary_extractor / dispute_matrix / consensus_map（覆盖补齐）。"""

from __future__ import annotations

import pytest

from more_core.core.types import LayerId, ReasoningStep
from more_core.council.consensus_map import (
    ConsensusMap,
    _extract_topic,
    build_consensus_map,
)
from more_core.council.dispute_matrix import DisputeMatrix
from more_core.council.summary_extractor import summarize_outputs, summarize_role_output

_ROLE = {
    "role": "analyst",
    "core_judgment": "整体可行",
    "top_concern": "成本偏高",
    "constructive_suggestion": "先做小规模验证",
    "key_arguments": [{"point": "p1"}, {"point": "p2"}, "p3", {"point": "p4"}],
}


# ---------------------------------------------------------------------------
# summary_extractor
# ---------------------------------------------------------------------------


def test_summarize_full_returns_raw():
    assert summarize_role_output(_ROLE, "full") == str(_ROLE)


def test_summarize_one_line():
    out = summarize_role_output(_ROLE, "one_line")
    assert out.startswith("[analyst]") and "整体可行" in out
    assert summarize_role_output({"role": "r"}, "one_line") == "[r] (无核心判断)"


def test_summarize_three_sentences():
    out = summarize_role_output(_ROLE, "three_sentences")
    assert "核心判断" in out and "关注点" in out and "建议" in out
    assert summarize_role_output({"role": "r"}, "three_sentences") == "[r] (无内容)"


def test_summarize_compact_limits_arguments_to_three():
    out = summarize_role_output(_ROLE, "compact")
    assert out.startswith("=== analyst ===")
    assert "论点1" in out and "论点3" in out
    assert "论点4" not in out, "紧凑摘要最多保留 3 条论点"


def test_summarize_compact_handles_string_arguments():
    out = summarize_role_output({"role": "r", "key_arguments": ["纯字符串"]}, "compact")
    assert "纯字符串" in out


def test_unknown_level_falls_back_to_compact():
    out = summarize_role_output(_ROLE, "bogus")
    assert out.startswith("=== analyst ===")


def test_summarize_outputs_empty():
    assert summarize_outputs([]) == "(无输出)"


def test_summarize_outputs_joins_with_separator():
    out = summarize_outputs([{"role": "a"}, {"role": "b"}], level="one_line")
    assert "---" in out and "[a]" in out and "[b]" in out


def test_summarize_outputs_downgrades_when_over_budget():
    outputs = [dict(_ROLE, role=f"r{i}") for i in range(6)]
    out = summarize_outputs(outputs, level="compact", max_total_chars=200)
    assert "=== r0 ===" not in out, "超预算应自动降级压缩级别"
    assert len(out) <= 200 + len("\n...(截断)")


def test_summarize_outputs_truncates_when_still_over():
    outputs = [{"role": "r", "core_judgment": "x" * 500} for _ in range(5)]
    out = summarize_outputs(outputs, level="one_line", max_total_chars=100)
    assert out.endswith("...(截断)")


# ---------------------------------------------------------------------------
# dispute_matrix
# ---------------------------------------------------------------------------


def _outputs() -> list[dict]:
    return [
        {
            "role": "critic",
            "core_judgment": "风险较大",
            "directed_response": {
                "target_role": "architect",
                "target_point": "微服务拆分",
                "stance": "oppose",
            },
        },
        {
            "role": "architect",
            "core_judgment": "方案可行，推荐推进",
        },
        {"role": "quiet", "core_judgment": "无意见"},
    ]


def test_dispute_matrix_from_outputs_infers_target_stance():
    dm = DisputeMatrix.from_outputs(_outputs())
    assert len(dm.entries) == 1
    e = dm.entries[0]
    assert e["role_a"] == "critic" and e["role_b"] == "architect"
    assert e["stance_a"] == "oppose"
    assert e["stance_b"] == "support"  # 由 architect 的 core_judgment 推断
    assert e["resolved"] is False


def test_dispute_matrix_dedupes_same_pair_topic():
    dup = _outputs()
    dup.append(dict(dup[0]))
    dm = DisputeMatrix.from_outputs(dup)
    assert len(dm.entries) == 1


def test_dispute_matrix_skips_without_directed_response():
    dm = DisputeMatrix.from_outputs([{"role": "a", "core_judgment": "x"}])
    assert dm.entries == []
    assert dm.summary["total_conflicts"] == 0


def test_dispute_matrix_summary_and_to_dict():
    dm = DisputeMatrix.from_outputs(_outputs())
    assert dm.summary["total_conflicts"] == 1
    assert dm.summary["unresolved"] == 1
    d = dm.to_dict()
    assert set(d) == {"entries", "summary"}


def test_dispute_matrix_neutral_when_target_unknown():
    outputs = [
        {"role": "a", "directed_response": {"target_role": "ghost", "target_point": "t"}},
    ]
    dm = DisputeMatrix.from_outputs(outputs)
    assert dm.entries[0]["stance_b"] == "neutral"


# ---------------------------------------------------------------------------
# consensus_map
# ---------------------------------------------------------------------------


def _step(i: int, layer: LayerId, desc: str) -> ReasoningStep:
    return ReasoningStep(id=i, layer=layer, description=desc, duration_ms=1.0)


def test_consensus_map_consensus_item_when_multiple_layers():
    chain = [
        _step(1, LayerId.L4, "统一主题。细节A"),
        _step(2, LayerId.L1, "统一主题。细节B"),
    ]
    cmap = build_consensus_map(chain)
    assert cmap.consensus_items, "多层参与应产出共识条目"
    assert "共 2 层参与推理" in cmap.consensus_items[0]


def test_consensus_map_single_layer_has_no_consensus_item():
    cmap = build_consensus_map([_step(1, LayerId.L4, "只有一层")])
    assert cmap.consensus_items == []


def test_consensus_map_detects_dispute_on_shared_topic():
    chain = [
        _step(1, LayerId.L4, "统一主题。观点A"),
        _step(2, LayerId.L1, "统一主题。观点B"),
    ]
    cmap = build_consensus_map(chain)
    assert len(cmap.stances) == 1, "同主题应合并为一条立场记录"
    assert set(cmap.stances[0]["layer_stances"]) == {"L4", "L1"}
    assert len(cmap.key_disputes) == 1
    assert cmap.key_disputes[0]["resolved"] is False


def test_consensus_map_distinct_topics_no_dispute():
    chain = [
        _step(1, LayerId.L4, "主题甲。x"),
        _step(2, LayerId.L1, "主题乙。y"),
    ]
    cmap = build_consensus_map(chain)
    assert cmap.key_disputes == []


def test_consensus_map_to_dict_shape():
    cmap = build_consensus_map([_step(1, LayerId.L4, "t。x")])
    assert isinstance(cmap, ConsensusMap)
    assert set(cmap.to_dict()) == {
        "stances",
        "key_disputes",
        "consensus_items",
        "minority_opinions",
    }


@pytest.mark.parametrize(
    "text,expected",
    [
        ("标题。后续", "标题"),
        ("标题，后续", "标题"),
        ("标题.后续", "标题"),
        ("标题\n后续", "标题"),
        ("没有分隔符的主题", "没有分隔符的主题"),
    ],
)
def test_extract_topic_separators(text, expected):
    assert _extract_topic(text) == expected


def test_extract_topic_respects_max_len():
    assert len(_extract_topic("x" * 200, max_len=10)) == 10
