"""L4→L5 Council 复评量化基线（高风险 / 分歧 → 置信度下修）。

固化 :meth:`MetacognitionLayer._review_council_output` 的数值契约，并验证该
结果会写入治理看板遥测（``council_reviews``）。

下修公式（基线）::

    adjustment = 0
    分歧(divided):            -0.15     ；弱共识(weak): -0.08
    高风险(severity=high):    -0.05 × min(n, 3)
    乐观放大风险:              risk_count ≥ 3 且 alignment > 0.85 → -0.05
    council 错误:             -0.05 × min(n_errors, 3)
    下限 clamp:               max(adjustment, -0.5)
"""

from __future__ import annotations

import pytest

from more_core.core.types import LayerId, TaskRequest, TaskType
from more_core.governance import observability as obs
from more_core.layers.base import LayerContext
from more_core.layers.l5_metacognition import MetacognitionLayer


class _Council:
    """最小 CouncilResult 替身（只含复评用到的字段）。"""

    def __init__(self, consensus="strong", risks=None, errors=None, conclusion="ok"):
        self.synthesis = {"risk_assessment": list(risks or [])}
        self.consensus_level = consensus
        self.errors = list(errors or [])
        self.core_conclusion = conclusion


def _high(n):
    return [{"severity": "high", "risk": f"r{i}"} for i in range(n)]


def _medium(n):
    return [{"severity": "medium", "risk": f"m{i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# 量化基线矩阵：分歧 / 高风险 / 错误 / 乐观放大 的精确下修值
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "consensus,risks,errors,alignment,expected",
    [
        # 无风险：只有共识级别影响
        ("strong", [], [], 0.80, 0.0),
        ("moderate", [], [], 0.80, 0.0),
        ("weak", [], [], 0.80, -0.08),
        ("divided", [], [], 0.80, -0.15),
        # 高风险按项累计、封顶 3 项
        ("strong", _high(1), [], 0.80, -0.05),
        ("strong", _high(3), [], 0.80, -0.15),
        ("strong", _high(5), [], 0.80, -0.15),
        # 分歧 + 高风险叠加
        ("divided", _high(2), [], 0.80, -0.25),
        # 分歧 + 3 高风险 + 乐观放大（alignment > 0.85）
        ("divided", _high(3), [], 0.90, -0.35),
        # 错误按条累计、封顶 3 条
        ("strong", [], ["e"] * 3, 0.80, -0.15),
        # 全叠加 → 恰好触达下限 -0.5
        ("divided", _high(3) + _medium(1), ["e"] * 3, 0.90, -0.50),
    ],
)
def test_review_adjustment_baseline(consensus, risks, errors, alignment, expected):
    review = MetacognitionLayer._review_council_output(
        _Council(consensus=consensus, risks=risks, errors=errors),
        calibration={"alignment": alignment},
        current_alignment=alignment,
    )
    assert review["confidence_adjustment"] == pytest.approx(expected), review["adjustment_reason"]


def test_review_reports_full_counts_even_when_risks_truncated():
    """risks 列表截断到 5，但计数必须是完整值（供遥测与看板使用）。"""
    review = MetacognitionLayer._review_council_output(
        _Council(consensus="divided", risks=_high(8)),
        calibration={},
        current_alignment=0.9,
    )
    assert len(review["risks"]) == 5        # 回传截断
    assert review["risk_count"] == 8        # 计数完整
    assert review["high_risk_count"] == 8


def test_no_risks_no_errors_strong_is_neutral():
    review = MetacognitionLayer._review_council_output(
        _Council(consensus="strong"), calibration={}, current_alignment=0.9
    )
    assert review["confidence_adjustment"] == 0.0
    assert "no adjustment needed" in review["adjustment_reason"]


# ---------------------------------------------------------------------------
# 集成：L5 应用下修并把复评写入遥测
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l5_applies_downgrade_and_records_telemetry(core):
    layer = core.get_layer(LayerId.L5)
    council = _Council(consensus="divided", risks=_high(2))
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query="x"))
    ctx.scratch["plan"] = {
        "decomposed": True, "subtasks": ["a"], "council_result": council,
    }

    result = await layer.run(ctx)

    review = ctx.scratch["council_review"]
    assert review["confidence_adjustment"] == pytest.approx(-0.25)
    # 输出置信度反映下修（不为负）
    assert 0.0 <= result.confidence <= 1.0

    st = obs.query_council_stats(3600)
    assert st["reviews"] == 1
    assert st["downgraded"] == 1
    assert st["downgrade_rate"] == 1.0
    assert st["divided"] == 1
    assert st["high_risk_reviews"] == 1
    assert st["avg_adjustment"] == pytest.approx(-0.25)


@pytest.mark.asyncio
async def test_no_council_result_records_nothing(core):
    layer = core.get_layer(LayerId.L5)
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query="x"))
    await layer.run(ctx)
    assert obs.query_council_stats(3600)["reviews"] == 0


# ---------------------------------------------------------------------------
# 遥测聚合口径
# ---------------------------------------------------------------------------


def test_council_stats_aggregation():
    obs.record_council_review(request_id="a", consensus="strong", adjustment=0.0)
    obs.record_council_review(request_id="b", consensus="divided", adjustment=-0.25, high_risks=2)
    obs.record_council_review(request_id="c", consensus="weak", adjustment=-0.08)

    st = obs.query_council_stats(3600)
    assert st["reviews"] == 3
    assert st["downgraded"] == 2
    assert st["downgrade_rate"] == pytest.approx(0.667, abs=1e-3)
    assert st["divided"] == 1
    assert st["weak"] == 1
    assert st["high_risk_reviews"] == 1
    assert st["min_adjustment"] == pytest.approx(-0.25)
    assert st["by_consensus"]["strong"] == 1


def test_council_stats_empty_is_zero_not_error():
    st = obs.query_council_stats(3600)
    assert st["reviews"] == 0
    assert st["downgrade_rate"] == 0.0
    assert "error" not in st


# ---------------------------------------------------------------------------
# 接口：JSON + Prometheus
# ---------------------------------------------------------------------------


def test_council_metrics_endpoint(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    obs.record_council_review(request_id="b", consensus="divided", adjustment=-0.25, high_risks=2)

    with TestClient(create_app(core)) as client:
        resp = client.get("/api/v1/metrics/council?window_s=3600")
    assert resp.status_code == 200
    m = resp.json()["metrics"]
    assert m["reviews"] == 1
    assert m["divided"] == 1
    assert m["downgrade_rate"] == 1.0


def test_prometheus_exports_council_metrics(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    obs.record_council_review(request_id="b", consensus="divided", adjustment=-0.25, high_risks=2)

    with TestClient(create_app(core)) as client:
        resp = client.get("/api/v1/metrics/governance/prometheus?window_s=3600")
    assert resp.status_code == 200
    body = resp.text
    assert "more_os_council_reviews 1" in body
    assert "more_os_council_downgrade_rate 1.0" in body
    assert 'more_os_council_reviews_by_consensus{consensus="divided"} 1' in body
