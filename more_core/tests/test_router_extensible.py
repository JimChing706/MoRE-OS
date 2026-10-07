"""Tests for the extensible LayerRouter (L3 fix regression + new features)."""

from __future__ import annotations

import pytest

from more_core.core.config import Settings
from more_core.core.errors import RoutingError
from more_core.core.types import LayerId, TaskRequest, TaskType
from more_core.router.layer_router import DEFAULT_PIPELINES, LayerRouter


def _settings(**overrides: object) -> Settings:
    base = dict(
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Settings-driven custom pipeline
# ---------------------------------------------------------------------------


def test_custom_pipeline_from_settings() -> None:
    """custom_pipelines in Settings should override the built-in default."""
    s = _settings(custom_pipelines={"nlp_task": ["L4", "L0"]})
    router = LayerRouter(s)
    dec = router.route(TaskRequest(type=TaskType.NLP_TASK, query="hi"))
    # L3 and L1 should be absent because we overrode with [L4, L0]
    assert dec.pipeline == [LayerId.L4, LayerId.L0]


# ---------------------------------------------------------------------------
# Plugin extension API
# ---------------------------------------------------------------------------


def test_register_pipeline_overrides_type() -> None:
    router = LayerRouter(_settings())
    router.register_pipeline(TaskType.NLP_TASK, [LayerId.L4, LayerId.L0])
    dec = router.route(TaskRequest(type=TaskType.NLP_TASK, query="hi"))
    assert dec.pipeline == [LayerId.L4, LayerId.L0]


def test_register_pipeline_rejects_missing_l0() -> None:
    router = LayerRouter(_settings())
    with pytest.raises(RoutingError, match="L0"):
        router.register_pipeline(TaskType.NLP_TASK, [LayerId.L4, LayerId.L3])


def test_unregister_pipeline_reverts_to_default() -> None:
    router = LayerRouter(_settings())
    router.register_pipeline(TaskType.NLP_TASK, [LayerId.L4, LayerId.L0])
    router.unregister_pipeline(TaskType.NLP_TASK)
    dec = router.route(TaskRequest(type=TaskType.NLP_TASK, query="hi"))
    assert dec.pipeline == list(DEFAULT_PIPELINES[TaskType.NLP_TASK])


def test_list_pipelines_returns_all() -> None:
    router = LayerRouter(_settings())
    pipelines = router.list_pipelines()
    assert "nlp_task" in pipelines
    assert "self_improvement" in pipelines
    assert all(isinstance(v, list) for v in pipelines.values())


def test_register_plugin_defined_type() -> None:
    """Plugins should be able to register a custom pipeline for PLUGIN_DEFINED."""
    router = LayerRouter(_settings())
    router.register_pipeline(TaskType.PLUGIN_DEFINED, [LayerId.L4, LayerId.L3, LayerId.L0])
    dec = router.route(TaskRequest(type=TaskType.PLUGIN_DEFINED, query="test"))
    assert LayerId.L3 in dec.pipeline


# ---------------------------------------------------------------------------
# Feature-gate interaction with custom pipelines
# ---------------------------------------------------------------------------


def test_custom_pipeline_respects_feature_gates() -> None:
    """Even if a custom pipeline includes L3, disabling symbolic should remove it."""
    s = _settings(
        enable_symbolic=False,
        custom_pipelines={"nlp_task": ["L4", "L3", "L1", "L0"]},
    )
    router = LayerRouter(s)
    dec = router.route(TaskRequest(type=TaskType.NLP_TASK, query="hi"))
    assert LayerId.L3 not in dec.pipeline


def test_default_pipelines_unchanged_after_register() -> None:
    """register_pipeline on an instance must not mutate the module-level defaults."""
    router = LayerRouter(_settings())
    original = list(DEFAULT_PIPELINES[TaskType.NLP_TASK])
    router.register_pipeline(TaskType.NLP_TASK, [LayerId.L4, LayerId.L0])
    assert DEFAULT_PIPELINES[TaskType.NLP_TASK] == original
