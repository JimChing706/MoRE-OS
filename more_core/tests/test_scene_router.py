"""场景自适应路由（P5 scene_router）测试。

背景：该模块此前仅被无调用方的 `LayerRouter.route_with_scene()` 引用，
覆盖率 **0%**（评估发现 A-2）。现通过 `/router/scene` 内省端点接通，并补全覆盖。
"""

from __future__ import annotations

import pytest

from more_core.core.types import LayerId, TaskRequest, TaskType
from more_core.router.scene_router import (
    PipelineHint,
    _classify,
    _load_config,
    apply_scene_hint,
    resolve_scene,
)

# ---------------------------------------------------------------------------
# 配置加载（含容错降级）
# ---------------------------------------------------------------------------


def test_load_config_missing_file_falls_back(tmp_path):
    cfg = _load_config(tmp_path / "nope.yaml")
    assert isinstance(cfg, dict)
    assert "scenes" in cfg and "general" in cfg["scenes"]


def test_load_config_invalid_yaml_falls_back(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("scenes: [this is: not valid", encoding="utf-8")
    cfg = _load_config(bad)
    assert "scenes" in cfg, "解析失败应降级到默认配置"


def test_load_config_empty_file_falls_back(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert "scenes" in _load_config(empty)


# ---------------------------------------------------------------------------
# 分类与评分
# ---------------------------------------------------------------------------


def test_classify_scores_by_hit_count():
    label1, conf1, hits1 = _classify("架构")
    assert label1 == "code_architecture"
    assert conf1 == pytest.approx(0.62) and hits1 == ["架构"]

    label2, conf2, hits2 = _classify("架构 重构")
    assert label2 == "code_architecture"
    assert conf2 == pytest.approx(0.74) and len(hits2) == 2


def test_classify_no_hit_is_general():
    label, conf, hits = _classify("完全无关的一句话 zzz")
    assert label == "general" and conf == 0.5 and hits == []


def test_classify_is_case_insensitive():
    assert _classify("fix this BUG")[0] == "code_debugging"


# ---------------------------------------------------------------------------
# resolve_scene
# ---------------------------------------------------------------------------


def test_resolve_scene_architecture_prepends_l5():
    d = resolve_scene("重构这个系统的架构")
    assert d.label == "code_architecture"
    assert d.mode == "deep"
    assert LayerId.L5 in d.pipeline_hint.prepend
    assert d.needs_clarification is False


def test_resolve_scene_debugging_skips_symbolic_and_metacog():
    d = resolve_scene("修复这个 bug")
    assert d.label == "code_debugging"
    assert d.mode == "quick"
    assert {LayerId.L3, LayerId.L5} <= set(d.pipeline_hint.skip)


def test_resolve_scene_security_prepends_and_appends():
    d = resolve_scene("这是安全加密认证相关")
    assert d.label == "security_critical"
    assert LayerId.L5 in d.pipeline_hint.prepend
    assert LayerId.L2 in d.pipeline_hint.append


def test_scene_decision_to_dict_shape():
    d = resolve_scene("架构")
    out = d.to_dict()
    assert set(out) >= {
        "label",
        "confidence",
        "needs_clarification",
        "matched_keywords",
        "mode",
        "pipeline_hint",
        "output_focus",
        "description",
    }
    assert set(out["pipeline_hint"]) == {"prepend", "append", "skip"}
    assert all(isinstance(v, str) for v in out["pipeline_hint"]["prepend"])


# ---------------------------------------------------------------------------
# apply_scene_hint（不覆盖，只调整）
# ---------------------------------------------------------------------------

_BASE = [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0]


def test_apply_hint_prepend():
    out = apply_scene_hint(_BASE, PipelineHint(prepend=[LayerId.L5]))
    assert out[0] == LayerId.L5
    assert out[-1] == LayerId.L0


def test_apply_hint_skip():
    out = apply_scene_hint(_BASE, PipelineHint(skip=[LayerId.L3]))
    assert LayerId.L3 not in out


def test_apply_hint_append_goes_before_l0():
    out = apply_scene_hint(_BASE, PipelineHint(append=[LayerId.L2]))
    assert out.index(LayerId.L2) == out.index(LayerId.L0) - 1
    assert out[-1] == LayerId.L0


def test_apply_hint_prepend_dedupes():
    out = apply_scene_hint(_BASE, PipelineHint(prepend=[LayerId.L4, LayerId.L5]))
    assert out.count(LayerId.L4) == 1
    assert out[0] == LayerId.L5


def test_apply_hint_always_ends_with_l0():
    out = apply_scene_hint([LayerId.L4, LayerId.L1], PipelineHint())
    assert out[-1] == LayerId.L0


def test_apply_hint_reorders_l0_to_end():
    out = apply_scene_hint([LayerId.L0, LayerId.L4], PipelineHint())
    assert out[-1] == LayerId.L0


# ---------------------------------------------------------------------------
# LayerRouter.route_with_scene + API 端点
# ---------------------------------------------------------------------------


def test_route_with_scene_applies_hint_and_reports_scene(core):
    decision = core.router.route_with_scene(
        TaskRequest(type=TaskType.CODE_GENERATION, query="重构这个系统的架构")
    )
    assert LayerId.L5 in decision.pipeline
    assert "scene=" in decision.reasoning
    assert LayerId.L0 == decision.pipeline[-1]


def test_router_scene_endpoint(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        body = client.get("/api/v1/router/scene", params={"q": "重构这个系统的架构"}).json()
        assert body["status"] == "ok"
        assert body["scene"]["label"] == "code_architecture"
        assert "L5" in body["scene_pipeline"]
        assert body["scene_pipeline"][-1] == "L0"
        # 非法 task_type
        assert (
            client.get("/api/v1/router/scene", params={"q": "x", "task_type": "nope"}).status_code
            == 422
        )
