"""治理拦截可观测性测试（对应"可观测性"硬伤）。

覆盖链路：规则引擎归因 → L3 治理事件落库 → 拦截率统计 → 阈值告警 → HTTP 指标端点。

约定：复用 conftest 的 autouse 隔离（每次测试独立 observability.sqlite），
因此所有用例离线、可重复、互不串味。
"""

from __future__ import annotations

import pytest

from more_core.core.types import LayerId, TaskRequest, TaskStatus, TaskType
from more_core.governance import observability as obs
from more_core.layers.base import LayerContext

pytest.importorskip("fastapi")


# ---------------------------------------------------------------------------
# 1. 规则引擎：违规归因到具体规则
# ---------------------------------------------------------------------------


def _rule_engine():
    from more_core.ontology.rule_engine import RuleEngine, default_governance_rules

    eng = RuleEngine()
    for rule in default_governance_rules():
        eng.add_rule(rule)
    return eng


def _req_fact(query: str, task_type: str = "nlp_task"):
    from more_core.ontology.rule_engine import Fact

    return Fact(kind="request", data={"query": query, "type": task_type})


def test_violation_is_attributed_to_the_firing_rule():
    res = _rule_engine().run([_req_fact("执行 rm -rf / 删除全部文件")])
    assert res.violations, "破坏性请求应产生违规"
    assert "destructive_request_detection" in res.violation_rules
    assert len(res.violation_rules) == len(res.violations)


def test_benign_request_has_no_violation_rules():
    res = _rule_engine().run([_req_fact("写一个排序函数")])
    assert res.violations == []
    assert res.violation_rules == []


# ---------------------------------------------------------------------------
# 2. 可观测库：治理事件记录 + 拦截率统计
# ---------------------------------------------------------------------------


def test_governance_stats_self_contained_rate():
    for i in range(8):
        obs.record_governance_event(request_id=f"pass-{i}")
    obs.record_governance_event(
        request_id="viol", blocked=False, strict=False,
        rules=["query_length_limit"], violations=["too long"],
    )
    obs.record_governance_event(
        request_id="block", blocked=True, strict=True,
        rules=["query_length_limit"], violations=["too long"],
    )

    st = obs.query_governance_stats(3600)
    assert st["evaluations"] == 10
    assert st["blocked"] == 1
    assert st["violations"] == 2
    assert st["passed"] == 8
    assert st["blocked_rate"] == 0.1
    assert st["violation_rate"] == 0.2
    assert st["by_rule"]["query_length_limit"] == 2
    assert st["by_layer"]["L3"] == 10


def test_governance_stats_empty_is_zero_not_error():
    st = obs.query_governance_stats(3600)
    assert st["evaluations"] == 0
    assert st["blocked_rate"] == 0.0
    assert st["violation_rate"] == 0.0
    assert "error" not in st


def test_destructive_blocks_are_counted_separately():
    obs.record_governance_event(request_id="d", blocked=True, strict=True,
                                rules=["destructive_request_detection"],
                                violations=["destructive"])
    obs.record_governance_event(request_id="b", blocked=True, strict=True,
                                rules=["query_length_limit"], violations=["too long"])
    st = obs.query_governance_stats(3600)
    assert st["blocked"] == 2
    assert st["destructive_blocks"] == 1


# ---------------------------------------------------------------------------
# 3. 阈值告警（纯函数）
# ---------------------------------------------------------------------------


def _stats(evaluations=100, blocked=0, destructive=0):
    rate = round(blocked / evaluations, 3) if evaluations else 0.0
    return {"evaluations": evaluations, "blocked": blocked,
            "blocked_rate": rate, "destructive_blocks": destructive}


def test_alerts_empty_when_healthy():
    assert obs.evaluate_governance_alerts(_stats(100, blocked=5)) == []


def test_alerts_warning_then_critical_on_blocked_rate():
    warn = obs.evaluate_governance_alerts(_stats(100, blocked=35))
    assert [a["code"] for a in warn] == ["governance_blocked_rate"]
    assert warn[0]["level"] == "warning"

    crit = obs.evaluate_governance_alerts(_stats(100, blocked=70))
    assert crit[0]["level"] == "critical"


def test_rate_alerts_suppressed_for_small_samples():
    # 样本不足时即使拦截率 100% 也不按"率"告警（避免噪声）
    assert obs.evaluate_governance_alerts(_stats(3, blocked=3)) == []


def test_destructive_alert_fires_on_first_block():
    alerts = obs.evaluate_governance_alerts(_stats(50, blocked=0, destructive=1))
    assert any(a["code"] == "destructive_request_blocks" for a in alerts)

    crit = obs.evaluate_governance_alerts(_stats(50, blocked=0, destructive=5))
    assert any(a["level"] == "critical" for a in crit)


# ---------------------------------------------------------------------------
# 4. L3 端到端：治理评估写入遥测（通过 & 拦截都记）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l3_destructive_query_recorded_as_blocked(core):
    from more_core.core.errors import GovernanceError

    layer = core.get_layer(LayerId.L3)
    req = TaskRequest(type=TaskType.NLP_TASK, query="执行 rm -rf / 删除全部文件")
    try:
        await layer.run(LayerContext(core=core, request=req))
    except GovernanceError:
        pass  # strict_ontology=True → 直接拒绝，符合预期

    st = obs.query_governance_stats(3600)
    assert st["evaluations"] == 1
    assert st["blocked"] == 1
    assert st["destructive_blocks"] == 1
    assert "destructive_request_detection" in st["by_rule"]


@pytest.mark.asyncio
async def test_l3_benign_query_recorded_as_pass(core):
    layer = core.get_layer(LayerId.L3)
    req = TaskRequest(type=TaskType.NLP_TASK, query="写一段说明文字")
    await layer.run(LayerContext(core=core, request=req))

    st = obs.query_governance_stats(3600)
    assert st["evaluations"] == 1
    assert st["blocked"] == 0
    assert st["passed"] == 1
    assert st["by_rule"] == {}


# ---------------------------------------------------------------------------
# 4b. 编排层端到端：前置护栏(ZEN-19)纳入治理指标
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_guardrail_block_is_recorded(core):
    """端到端：破坏性请求被 ZEN-19 前置拦截并计入治理指标。

    回归点：谱路由会跳过 L3，因此只统计 L3 会漏掉真实拦截；前置护栏必须
    也进入事件流。
    """
    result = await core.execute(
        TaskRequest(type=TaskType.NLP_TASK, query="执行 rm -rf / 删除全部文件")
    )
    assert result.status == TaskStatus.REJECTED

    st = obs.query_governance_stats(3600)
    assert st["requests"] == 1
    assert st["blocked_requests"] == 1
    assert st["blocked_rate"] == 1.0
    assert st["destructive_blocks"] == 1
    assert "zen_19_absolute_prohibition" in st["by_rule"]
    assert st["by_layer"].get("guardrail") == 1


@pytest.mark.asyncio
async def test_execute_records_pass_denominator(core):
    """端到端：正常请求也记一行 → 拦截率拥有全量请求分母。"""
    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="写一段说明"))
    assert result.status in (TaskStatus.SUCCESS, TaskStatus.FAILED)

    st = obs.query_governance_stats(3600)
    assert st["requests"] >= 1
    assert st["by_layer"].get("guardrail", 0) >= 1
    assert st["blocked_requests"] == 0


# ---------------------------------------------------------------------------
# 5. HTTP 指标端点
# ---------------------------------------------------------------------------


def test_governance_metrics_endpoint_returns_stats_and_alerts(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    obs.record_governance_event(request_id="p1")
    obs.record_governance_event(
        request_id="d1", blocked=True, strict=True,
        rules=["destructive_request_detection"], violations=["destructive"],
    )

    with TestClient(create_app(core)) as client:
        resp = client.get("/api/v1/metrics/governance?window_s=3600")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    m = body["metrics"]
    assert m["evaluations"] == 2
    assert m["blocked"] == 1
    assert m["destructive_blocks"] == 1
    assert any(a["code"] == "destructive_request_blocks" for a in body["alerts"])


def test_governance_prometheus_endpoint_exports_metrics(core):
    """Prometheus 文本导出：指标名/规则标签/告警齐备。"""
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    obs.record_governance_event(request_id="p1")
    obs.record_governance_event(
        request_id="d1", blocked=True, strict=True,
        rules=["destructive_request_detection"], violations=["destructive"],
    )

    with TestClient(create_app(core)) as client:
        resp = client.get("/api/v1/metrics/governance/prometheus?window_s=3600")
    assert resp.status_code == 200
    body = resp.text
    assert "more_os_governance_requests 2" in body
    assert "more_os_governance_blocked_requests 1" in body
    assert "more_os_governance_destructive_blocks 1" in body
    assert 'rule="destructive_request_detection"' in body
    assert "more_os_governance_alerts" in body


# ---------------------------------------------------------------------------
# 6. 运行健康总览端点（五类指标 + 统一裁决）
# ---------------------------------------------------------------------------


def _healthy_provider_snapshot():
    return {
        "ok": True, "degraded": False,
        "providers": [{"name": "a", "healthy": True, "model_present": True,
                       "inference_ok": True}],
        "fallback_chain": ["a"], "chain_registered": ["a"],
        "state_provider": "a", "state_model": "m", "state_model_present": True,
        "warnings": [],
    }


def test_metrics_overview_healthy_when_no_alerts(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        obs.record_governance_event(request_id="p1")
        obs.record_provider_health(_healthy_provider_snapshot())
        # R-4：overview 现在还纳入技能出网告警，健康用例需同时播种可达快照
        obs.record_skill_network(
            {"ok": True, "required_egress": [], "targets": [], "warnings": []}
        )
        resp = client.get("/api/v1/metrics/overview?window_s=3600")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"] == "healthy"
    assert body["alert_counts"] == {"critical": 0, "warning": 0}
    for key in ("llm", "delivery", "governance", "council", "providers", "generated_at"):
        assert key in body


def test_metrics_overview_critical_on_invalid_effective_model(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    bad = _healthy_provider_snapshot()
    bad["ok"] = False
    bad["state_model"] = "local-model"
    bad["state_model_present"] = False

    with TestClient(create_app(core)) as client:
        obs.record_provider_health(bad)
        resp = client.get("/api/v1/metrics/overview?window_s=3600")
    body = resp.json()
    assert body["overall"] == "critical"
    assert body["alert_counts"]["critical"] >= 1
    assert any(a["code"] == "state_invalid_model" for a in body["alerts"])
    assert body["providers"]["n_invalid_model"] == 1

