"""Tests for repo-aware code generation context (BPR B)."""

from __future__ import annotations

from more_core.codegen.context import build_repo_context
from more_core.core.types import TaskRequest, TaskType
from more_core.layers.base import LayerContext
from more_core.layers.l0_execution import ExecutionLayer


def test_build_repo_context_empty_without_root():
    assert build_repo_context(None) == ""
    assert build_repo_context("") == ""
    assert build_repo_context("/nonexistent/root/xyz") == ""


def test_build_repo_context_scans_modules(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "service.py").write_text(
        "def make_client():\n    return 1\n\n"
        "class Service:\n    pass\n\n"
        "@router.get('/health')\n"
        "def health():\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    ctx = build_repo_context(str(tmp_path))
    assert "pkg/service.py" in ctx
    assert "make_client" in ctx
    assert "Service" in ctx
    assert "GET /health" in ctx
    assert ctx.startswith("<repo_context>")


def test_build_repo_context_skips_noise_dirs(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "junk.py").write_text("x = 1", encoding="utf-8")
    ctx = build_repo_context(str(tmp_path))
    assert ".venv/junk.py" not in ctx


def test_build_repo_context_caps_files(tmp_path):
    for i in range(5):
        (tmp_path / f"m{i}.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ctx = build_repo_context(str(tmp_path), max_files=2)
    assert ctx.count("- ") == 2


def test_l0_repo_context_skipped_without_root(core):
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.CODE_GENERATION, query="x"))
    assert ExecutionLayer._build_repo_context(ctx) == ""


def test_l0_repo_context_injected_when_root_available(tmp_path):
    (tmp_path / "mod.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    core = _core_with_root(tmp_path)
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.CODE_GENERATION, query="x"))
    out = ExecutionLayer._build_repo_context(ctx)
    assert "mod.py" in out
    assert "helper" in out


def test_l0_repo_context_respects_feature_gate(tmp_path):
    (tmp_path / "mod.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    core = _core_with_root(tmp_path)
    core.settings.enable_codegen_context = False
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.CODE_GENERATION, query="x"))
    assert ExecutionLayer._build_repo_context(ctx) == ""


def _core_with_root(tmp_path):
    from more_core.runtime.orchestrator import MoRECore

    core = MoRECore.__new__(MoRECore)
    core.settings = type("S", (), {"enable_codegen_context": True})()
    core.project_root = tmp_path
    return core
