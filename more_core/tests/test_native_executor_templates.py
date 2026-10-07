"""T0~T6 native_executor hardening tests (types/planner/writer/dispatcher/validator/provenance/status)."""


def test_types_import_and_blocking_level_hard_block_default():
    from more_core.core.native_executor.types import (
        ValidationBlockingLevel,
        AggregatedValidationResult,
        TemplateDispatchResult,
    )

    assert ValidationBlockingLevel.HARD_BLOCK.value == "hard_block"
    assert AggregatedValidationResult.__dataclass_fields__
    assert issubclass(TemplateDispatchResult, object)
    assert issubclass(ValidationBlockingLevel, str)


def test_dispatch_cs_shooter_key_match():
    from more_core.core.native_executor.planner import TaskTemplateSelector

    doc = (
        "---\ntitle: CS 射击游戏 Rust+前端\ntype: code_generation\ntags: [shooter, cs]\n---\n"
        "# Executive Summary \n## REQ-001 axum WebGL\n"
    )
    selector = TaskTemplateSelector()
    key = selector.key_for(task_request=None, doc=doc)
    assert key == "cs_shooter"


def test_dispatch_tetris_key_match_when_title_has_tetris():
    from more_core.core.native_executor.planner import TaskTemplateSelector

    doc = "---\ntitle: 俄罗斯方块 Rust+前端\ntype: code_generation\n---\n## REQ-001 俄罗斯方块 7 Bag\n"
    selector = TaskTemplateSelector()
    key = selector.key_for(task_request=None, doc=doc)
    assert key == "tetris"


def test_dispatch_generic_when_no_match():
    from more_core.core.native_executor.planner import TaskTemplateSelector

    doc = "---\ntitle: 区块链浏览器 API Server\ntype: code_generation\ntags: [backend]\n---\n"
    selector = TaskTemplateSelector()
    key = selector.key_for(task_request=None, doc=doc)
    assert key == "generic"


def test_cs_shooter_payload_has_no_tetris():
    from more_core.core.native_executor.payload_mixins import CSShooterWriterMixin

    mixin = CSShooterWriterMixin()
    payload = mixin.build_payload_map(task_request=None, doc=None, steps=[])
    for path in payload.keys():
        assert "tetris" not in path.lower(), f"CS payload 泄漏 Tetris 路径: {path}"
    assert any(p.startswith("shooter_core/") for p in payload)
    assert any(p.startswith("shooter_server/") for p in payload)
    assert any(p.startswith("frontend/") for p in payload)
    assert "README.md" in payload and "deploy/Dockerfile" in payload


def test_tetris_payload_backward_compatible_exact_13_paths():
    from more_core.core.native_executor.payload_mixins import TetrisWriterMixin

    mixin = TetrisWriterMixin()
    payload = mixin.build_payload_map(task_request=None, doc=None, steps=[])
    expected = {
        "Cargo.toml",
        "Makefile",
        ".gitignore",
        "rust-toolchain.toml",
        "justfile",
        "src/lib.rs",
        "src/tests.rs",
        "frontend/index.html",
        "frontend/style.css",
        "frontend/settings.html",
        "js/tetris.js",
        "docs/USAGE.md",
        "docs/ARCHITECTURE.md",
    }
    assert set(payload.keys()) == expected, (
        f"差集 extra={set(payload) - expected} miss={expected - set(payload)}"
    )


def test_aggregated_validator_blocking_truth_table():
    from more_core.core.native_executor.types import ValidationBlockingLevel
    from more_core.core.native_executor.validator import aggregate_results
    from dataclasses import dataclass

    @dataclass
    class FakeVR:
        pass_: bool
        total_commands: int
        passed_commands: int
        command_results: list

    ok = FakeVR(True, 2, 2, [None, None])
    bad = FakeVR(False, 2, 1, [None, None])
    empty = FakeVR(True, 0, 0, [])

    # HARD_BLOCK: both ok → not block
    agg = aggregate_results(ok, empty, level=ValidationBlockingLevel.HARD_BLOCK)
    assert agg.pass_ is True
    assert agg.should_block_release is False

    # HARD_BLOCK: source fail → block
    agg = aggregate_results(bad, ok, level=ValidationBlockingLevel.HARD_BLOCK)
    assert agg.should_block_release is True

    # HARD_BLOCK: archive fail → block
    agg = aggregate_results(ok, bad, level=ValidationBlockingLevel.HARD_BLOCK)
    assert agg.should_block_release is True

    # WARN → never block
    agg = aggregate_results(bad, bad, level=ValidationBlockingLevel.WARN)
    assert agg.should_block_release is False


def test_provenance_blocked_when_final_status_failed_on_last_channel():
    from more_core.core.guardrails.provenance_audit import ProvenanceLayer

    layer = ProvenanceLayer(":memory:")
    layer.enroll("t_fake")
    layer.mark(
        "t_fake",
        "native_planner_loop",
        iterations=4,
        files_written=13,
        payload={"phase": "done", "iterations": 4},
    )
    layer.mark(
        "t_fake",
        "native_planner_loop",
        iterations=4,
        files_written=13,
        payload={"phase": "final", "final_status": "failed"},
    )
    report = layer.audit("t_fake")
    assert report.deliverable_blocked is True
    assert any("final_status=failed" in w for w in report.warnings)


def test_status_override_when_audit_blocked():
    from more_core.core.guardrails.provenance_audit import ProvenanceLayer

    layer = ProvenanceLayer(":memory:")
    layer.enroll("t_bad")
    layer.mark(
        "t_bad",
        "native_planner_loop",
        iterations=4,
        files_written=13,
        payload={"phase": "final", "validation_pass": False, "final_status": "failed"},
    )
    report, status, progress = layer.audit_with_status_override(
        "t_bad",
        raw_status="completed",
        raw_progress=100,
    )
    assert report.deliverable_blocked is True
    assert status == "failed"
    assert progress <= 90
