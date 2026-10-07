"""A-3：成功率"近 1h / 24h"双窗口 + 趋势。"""

from __future__ import annotations

import time

from more_core.codegen.delivery_ledger import DeliveryLedger
from more_core.governance import observability as obs


def _ledger(tmp_path) -> DeliveryLedger:
    return DeliveryLedger(tmp_path / "ledger.db")


def _age_deliveries(ledger: DeliveryLedger, hours: float) -> None:
    conn = ledger._conn
    conn.execute("UPDATE deliveries SET ts = ?", (time.time() - hours * 3600,))


def test_success_trend_states():
    assert obs.success_trend(0.9, 0.5, recent_samples=10) == "improving"
    assert obs.success_trend(0.4, 0.9, recent_samples=10) == "declining"
    assert obs.success_trend(0.50, 0.52, recent_samples=10) == "stable"


def test_success_trend_no_data_when_recent_empty():
    """无样本 ≠ 下降：近窗口 0 样本时必须返回 no_data，不得误报 declining。"""
    assert obs.success_trend(0.0, 0.9, recent_samples=0) == "no_data"


def test_delivery_windows_shape(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record(task_id="t1", status="delivered", task_type="code_generation")

    out = ledger.stats_windows()
    assert set(out) == {"windows", "trend"}
    assert set(out["windows"]) == {"1h", "24h"}
    assert out["windows"]["1h"]["total"] == 1
    assert out["trend"] in ("improving", "declining", "stable")


def test_delivery_trend_distinguishes_recent_from_historical(tmp_path):
    """近 1h 全成功、更早全失败 → 1h 成功率应高于 24h，趋势 improving。"""
    ledger = _ledger(tmp_path)
    # 旧样本（2h 前）：失败
    for i in range(6):
        ledger.record(task_id=f"old{i}", status="failed", task_type="code_generation")
    _age_deliveries(ledger, 2)
    # 新样本（当前）：成功
    for i in range(3):
        ledger.record(task_id=f"new{i}", status="delivered", task_type="code_generation")

    out = ledger.stats_windows()
    assert out["windows"]["1h"]["success_rate"] == 1.0
    assert out["windows"]["24h"]["total"] == 9
    assert out["windows"]["24h"]["success_rate"] < 1.0
    assert out["trend"] == "improving", out


def test_skill_trend_no_data_when_no_recent_runs():
    """近 1h 无技能执行 → trend 必须是 no_data（不是 declining）。"""
    for i in range(3):
        obs.record_skill_run(skill_id="s1", category="code", success=True, duration_ms=1.0)
    conn = obs._get_conn()
    conn.execute("UPDATE skill_runs SET ts = ?", (time.time() - 7200,))
    out = obs.query_skill_stats_windows()
    assert out["windows"]["1h"]["runs"] == 0
    assert out["trend"] == "no_data", out


def test_delivery_trend_no_data_when_no_recent_deliveries(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record(task_id="t1", status="delivered", task_type="code_generation")
    _age_deliveries(ledger, 2)
    out = ledger.stats_windows()
    assert out["windows"]["1h"]["total"] == 0
    assert out["trend"] == "no_data", out


def test_skill_windows_shape():
    obs.record_skill_run(skill_id="s1", category="code", success=True, duration_ms=5.0)
    out = obs.query_skill_stats_windows()

    assert set(out) == {"windows", "trend"}
    assert set(out["windows"]) == {"1h", "24h"}
    assert out["windows"]["1h"]["runs"] == 1
    assert out["windows"]["1h"]["success_rate"] == 1.0


def test_skill_trend_distinguishes_recent_from_historical():
    for i in range(4):
        obs.record_skill_run(skill_id="s1", category="code", success=False, duration_ms=1.0)
    conn = obs._get_conn()
    conn.execute("UPDATE skill_runs SET ts = ?", (time.time() - 7200,))
    for i in range(2):
        obs.record_skill_run(skill_id="s1", category="code", success=True, duration_ms=1.0)

    out = obs.query_skill_stats_windows()
    assert out["windows"]["1h"]["success_rate"] == 1.0
    assert out["windows"]["24h"]["runs"] == 6
    assert out["trend"] == "improving", out


# ---------------------------------------------------------------------------
# API 暴露
# ---------------------------------------------------------------------------


def test_delivery_stats_endpoint_exposes_windows(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        body = client.get("/api/v1/delivery/stats?window_s=86400").json()
    assert "windows" in body
    assert set(body["windows"]["windows"]) == {"1h", "24h"}
    assert body["windows"]["trend"] in ("improving", "declining", "stable", "no_data")


def test_skill_metrics_endpoint_exposes_windows(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        obs.record_skill_run(skill_id="s1", category="code", success=True, duration_ms=3.0)
        body = client.get("/api/v1/metrics/skills?window_s=3600").json()
    assert "windows" in body
    assert body["windows"]["windows"]["1h"]["runs"] >= 1


def test_overview_exposes_recent_dual_window(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        body = client.get("/api/v1/metrics/overview?window_s=3600").json()
    recent = body["recent"]
    for key in (
        "delivery_1h_success_rate",
        "delivery_24h_success_rate",
        "delivery_trend",
        "skills_1h_success_rate",
        "skills_24h_success_rate",
        "skills_trend",
    ):
        assert key in recent, key
