from more_core.core.config import Settings
from more_core.core.types import LayerId, TaskRequest, TaskType
from more_core.router.layer_router import LayerRouter


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


def test_routing_default_pipeline() -> None:
    router = LayerRouter(_settings())
    decision = router.route(TaskRequest(type=TaskType.NLP_TASK, query="hi"))
    assert decision.pipeline[-1] == LayerId.L0
    assert LayerId.L3 in decision.pipeline  # symbolic enabled
    assert LayerId.L2 not in decision.pipeline  # evolution off by default


def test_routing_with_metacognitive_monitoring_includes_L5() -> None:
    router = LayerRouter(_settings())
    req = TaskRequest(type=TaskType.NLP_TASK, query="hi", require_metacognitive_monitoring=True)
    decision = router.route(req)
    assert LayerId.L5 in decision.pipeline


def test_routing_with_evolution_enabled_keeps_L2() -> None:
    router = LayerRouter(_settings(enable_evolution=True, enable_metacognition=True))
    req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="improve")
    decision = router.route(req)
    assert LayerId.L2 in decision.pipeline


def test_routing_target_layer_descending_order() -> None:
    router = LayerRouter(_settings())
    req = TaskRequest(type=TaskType.NLP_TASK, query="hi", target_layer=LayerId.L1)
    decision = router.route(req)
    assert decision.pipeline == [LayerId.L4, LayerId.L1, LayerId.L0]


def test_routing_target_layer_l4_includes_all_layers() -> None:
    router = LayerRouter(_settings())
    req = TaskRequest(type=TaskType.NLP_TASK, query="hi", target_layer=LayerId.L4)
    decision = router.route(req)
    assert decision.pipeline == [
        LayerId.L4,
        LayerId.L3,
        LayerId.L2,
        LayerId.L1,
        LayerId.L0,
    ]


def test_routing_target_layer_l2_transitive() -> None:
    router = LayerRouter(_settings())
    req = TaskRequest(type=TaskType.NLP_TASK, query="hi", target_layer=LayerId.L2)
    decision = router.route(req)
    assert decision.pipeline == [LayerId.L4, LayerId.L2, LayerId.L1, LayerId.L0]


def test_routing_target_layer_l0() -> None:
    router = LayerRouter(_settings())
    req = TaskRequest(type=TaskType.NLP_TASK, query="hi", target_layer=LayerId.L0)
    decision = router.route(req)
    assert decision.pipeline == [LayerId.L4, LayerId.L0]
