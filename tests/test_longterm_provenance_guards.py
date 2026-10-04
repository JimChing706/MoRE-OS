"""TR-13 Long-term provenance guard tests — entry enrollment, external hints, counters."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure the repo root (and more_core package nested root) are importable
# regardless of the cwd from which pytest is launched.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_MORE_INNER = _REPO_ROOT / "more_core"
if str(_MORE_INNER) not in sys.path:
    sys.path.insert(0, str(_MORE_INNER))


def _import(*names: str):
    """Flexible import helper — tolerates more_core.X vs more_core.more_core.X."""
    last_exc: Exception | None = None
    for prefix in ("more_core.more_core.", "more_core."):
        full = prefix + names[0] if len(names) == 1 else prefix + names[0]
        try:
            mod = __import__(full, fromlist=names[1:])
            if len(names) == 1:
                return mod
            obj = mod
            for n in names[1:]:
                obj = getattr(obj, n)
            return obj
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    assert last_exc is not None
    raise last_exc


@pytest.fixture(autouse=True)
def _ensure_clean_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    monkeypatch.delenv("MORE_REQUIRE_API_KEY", raising=False)


@pytest.fixture
def prov_tmp_db(tmp_path: Path) -> str:
    db = tmp_path / "t13_prov.db"
    return str(db)


MODE_A_TETRIS_ITD = """---
title: T13 Tetris Native Test
version: 1.0.0
author: t13_tester
created: 2026-09-27T00:00:00Z
type: code_generation
priority: high
deliverable_kind: code
tags: [tetris, rust, web]
estimated_hours: 4.0
pipeline:
  mode: standard
target_confidence: 80.0
max_iterations: 5
timeout_s: 120.0
---

# Executive Summary

T13 long-guard test task: build a minimal Tetris web game.

# Requirements

## REQ-001: 7-bag random generator
**Priority:** HIGH
**Description:** 7种方块(I/O/T/S/Z/J/L)随机生成每7轮包含每种一次

**Acceptance Criteria:**
- [x] 7种方块完整
- [x] 每7轮无重复
- [x] 随机生成

## REQ-002: Canvas渲染引擎
**Priority:** HIGH
**Description:** HTML5 Canvas渲染引擎含阴影效果和下一方块预览

**Acceptance Criteria:**
- [x] 60fps Canvas渲染
- [x] 方块阴影Ghost
- [x] 下一方块预览窗口

# Deliverable Contract

**Kind:** code
**Required Dimensions:** core_output, reasoning, tests
**Minimum Output Length:** 100

**Acceptance Criteria:**
- [x] 产生可运行 Rust 工程
- [x] 包含单元测试

# Kill Criteria

| ID | Condition | Severity | Timeline | Fallback |
|----|-----------|----------|----------|----------|
| KC-001 | 300秒无进度 | fatal | immediate | 停止并审计 |

# Resource Budget

**Estimated Tokens:** 4,000
**Estimated Duration:** 15 minutes
**Max Iterations:** 4
"""


def test_tr13_1_import_parser_produces_parent_subtask_map(prov_tmp_db: str) -> None:
    """TR-13.1 ITD parser produces parent id + ≥2 subtasks which provenance enrolls."""
    ImportTaskParser = _import("core.import_task", "ImportTaskParser")
    ProvenanceLayer = _import("core.guardrails.provenance_audit", "ProvenanceLayer")

    parser = ImportTaskParser()
    doc = parser.parse(MODE_A_TETRIS_ITD)
    parent_id = doc.to_task_request().id
    assert parent_id, "parent task id must be non-empty"
    assert len(doc.requirements) >= 2, "Tetris ITD should have ≥2 requirements"
    sub_ids = [f"{parent_id}-{r.id}" for r in doc.requirements]
    assert len(set(sub_ids)) == len(doc.requirements)

    layer = ProvenanceLayer(prov_tmp_db)
    layer.enroll(parent_id, "pending")
    layer.mark(
        parent_id,
        "pending",
        payload={
            "origin": "http_post_tasks_itd_import",
            "requirements_count": len(doc.requirements),
            "auto_start": False,
            "title": doc.title,
        },
    )
    for sid, req in zip(sub_ids, doc.requirements):
        layer.enroll(sid, "pending")
        layer.mark(
            sid,
            "pending",
            payload={
                "origin": "http_post_tasks_itd_import_subtask",
                "parent_id": parent_id,
                "requirement_id": req.id,
            },
        )

    records = layer.list_records(parent_id)
    assert len(records) >= 2
    parent_origins = [
        r["payload"]["origin"]
        for r in records
        if isinstance(r.get("payload"), dict) and r["payload"].get("origin")
    ]
    assert "http_post_tasks_itd_import" in parent_origins

    sub_records = layer.list_records(sub_ids[0])
    sub_origins = [
        r["payload"]["origin"]
        for r in sub_records
        if isinstance(r.get("payload"), dict) and r["payload"].get("origin")
    ]
    assert "http_post_tasks_itd_import_subtask" in sub_origins

    audit = layer.audit(parent_id)
    assert audit.execution_channel == "pending"
    assert audit.deliverable_blocked is False


def test_tr13_2_execute_task_external_hint_payloads(prov_tmp_db: str) -> None:
    """TR-13.2 External HTTP execute routes stamp external_tool_chain with origin hints."""
    ProvenanceLayer = _import("core.guardrails.provenance_audit", "ProvenanceLayer")
    layer = ProvenanceLayer(prov_tmp_db)

    id_a = "t13_ext_id_execute_001"
    layer.enroll(id_a, "pending")
    layer.mark(
        id_a,
        "external_tool_chain",
        payload={
            "origin": "http_post_tasks_id_execute",
            "prior_status": "pending",
        },
    )
    layer.mark(
        id_a,
        "native_planner_loop",
        token_count=1800,
        files_written=12,
        iterations=4,
        payload={"phase": "delivery", "origin_inherited": "http_post_tasks_id_execute"},
    )

    records = layer.list_records(id_a)
    origins = [
        r["payload"].get("origin") for r in records if isinstance(r.get("payload"), dict)
    ]
    assert "http_post_tasks_id_execute" in origins

    id_b = "t13_ext_generic_execute_002"
    layer.mark(
        id_b,
        "external_tool_chain",
        token_count=700,
        payload={
            "origin": "http_post_tasks_execute",
            "task_label": "T13 orchestrator external invocation test",
        },
    )
    b_records = layer.list_records(id_b)
    b_origins = [
        r["payload"].get("origin") for r in b_records if isinstance(r.get("payload"), dict)
    ]
    assert "http_post_tasks_execute" in b_origins


def test_tr13_3_channel_counters_and_audit_blocking_rule(prov_tmp_db: str) -> None:
    """TR-13.3 Counters cover all VALID_CHANNELS + unknown+>4000 → deliverable_blocked."""
    ProvenanceLayer = _import("core.guardrails.provenance_audit", "ProvenanceLayer")
    VALID_CHANNELS, AUDIT_TOK_THR = _import(
        "core.guardrails.provenance_audit", "VALID_CHANNELS"
    ), _import("core.guardrails.provenance_audit", "_AUDIT_TOKEN_THRESHOLD")
    layer = ProvenanceLayer(prov_tmp_db)
    layer.reset()

    channel_taskid = {
        "pending": "t13c_pending_01",
        "native_planner_loop": "t13c_native_02",
        "external_tool_chain": "t13c_external_03",
        "unknown": "t13c_unknown_04",
    }
    for ch, tid in channel_taskid.items():
        layer.enroll(tid, "pending")
        layer.mark(tid, ch, token_count=300, files_written=0 if ch == "pending" else 5, iterations=1)

    counters = layer.get_channel_counters()
    for ch in VALID_CHANNELS:
        assert ch in counters, f"missing channel {ch}"
    assert counters["pending"] == 1
    assert counters["native_planner_loop"] == 1
    assert counters["external_tool_chain"] == 1
    assert counters["unknown"] == 1

    all_latest = layer.list_all_tasks(limit=100)
    task_ids = {r["task_id"] for r in all_latest}
    assert task_ids.issuperset(set(channel_taskid.values()))

    blocked_tid = "t13c_blocked_big_unknown"
    layer.enroll(blocked_tid, "pending")
    layer.mark(blocked_tid, "unknown", token_count=AUDIT_TOK_THR + 500)
    rep1 = layer.audit(blocked_tid)
    assert rep1.deliverable_blocked is True
    assert any("audit_needed" in w for w in rep1.warnings)

    small_unknown = "t13c_small_unknown_allowed"
    layer.enroll(small_unknown, "pending")
    layer.mark(small_unknown, "unknown", token_count=AUDIT_TOK_THR)
    rep2 = layer.audit(small_unknown)
    assert rep2.deliverable_blocked is False

    safe_native = "t13c_native_safe_big"
    layer.enroll(safe_native, "pending")
    layer.mark(safe_native, "native_planner_loop", token_count=AUDIT_TOK_THR * 5)
    rep3 = layer.audit(safe_native)
    assert rep3.deliverable_blocked is False
