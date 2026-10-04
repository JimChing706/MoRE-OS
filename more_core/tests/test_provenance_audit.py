"""Tests for Provenance audit layer — ProvenanceLayer.mark/enroll/audit.

Covers:
  * VALID_CHANNELS constants
  * enroll creates pending seed record
  * mark appends records and inherits fields
  * audit() deliverable_blocked rules (unknown + tokens>4000)
  * audit returns warnings, channel, counts
  * list_records / reset helpers
  * thread safety and persistence
  * invalid channel coerced to unknown
  * singleton get_default_layer()
  * AuditReport.to_dict()
  * API endpoint GET /tasks/{task_id}/audit via TestClient
  * v2 executor provenance enroll+mark path
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from more_core.core.guardrails.provenance_audit import (
    AuditReport,
    ProvenanceLayer,
    VALID_CHANNELS,
    get_default_layer,
)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def layer(tmp_path: Path) -> ProvenanceLayer:
    """Isolated provenance layer per test."""
    db = tmp_path / "prov.db"
    return ProvenanceLayer(db)


@pytest.fixture
def client_with_provenance(tmp_path: Path):
    """FastAPI TestClient with a MoRECore instance."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from more_core.api.server import create_app
    from more_core.core.config import Settings
    from more_core.runtime.orchestrator import MoRECore
    from conftest import _FakeLLMProvider

    settings = Settings(
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
    )
    core = MoRECore(settings)
    core.llm._providers["fake"] = _FakeLLMProvider()
    core.llm._fallback = ["fake"]
    app = create_app(core)
    with TestClient(app) as c:
        yield core, c


# =====================================================================
# VALID_CHANNELS / constants
# =====================================================================


class TestValidChannels:
    def test_valid_channels_contains_four_expected(self):
        for c in {"pending", "native_planner_loop", "external_tool_chain", "unknown"}:
            assert c in VALID_CHANNELS

    def test_valid_channels_size_is_four(self):
        assert len(VALID_CHANNELS) == 4


# =====================================================================
# enroll + list_records basics
# =====================================================================


class TestEnroll:
    def test_enroll_creates_seed_record(self, layer: ProvenanceLayer):
        layer.enroll("t1", "pending")
        rows = layer.list_records("t1")
        assert len(rows) == 1
        assert rows[0]["channel"] == "pending"
        assert rows[0]["seq"] == 0

    def test_enroll_is_idempotent(self, layer: ProvenanceLayer):
        layer.enroll("t1", "pending")
        layer.enroll("t1", "native_planner_loop")
        rows = layer.list_records("t1")
        assert len(rows) == 1, "Second enroll on same task_id should be IGNORE"
        assert rows[0]["channel"] == "pending"

    def test_enroll_invalid_channel_becomes_unknown(self, layer: ProvenanceLayer):
        layer.enroll("t1", "bogus_channel_xyz")  # type: ignore[arg-type]
        rows = layer.list_records("t1")
        assert rows[0]["channel"] == "unknown"


# =====================================================================
# mark — appending, inheriting latest fields
# =====================================================================


class TestMark:
    def test_mark_creates_record_if_missing(self, layer: ProvenanceLayer):
        layer.mark("t_new", channel="pending", token_count=0)
        rows = layer.list_records("t_new")
        assert len(rows) == 1
        assert rows[0]["seq"] == 1

    def test_mark_increments_seq(self, layer: ProvenanceLayer):
        layer.enroll("t1", "pending")
        layer.mark("t1", "native_planner_loop", token_count=100, iterations=1)
        layer.mark("t1", "native_planner_loop", token_count=200, iterations=2)
        rows = layer.list_records("t1")
        seqs = [r["seq"] for r in rows]
        assert seqs == [0, 1, 2]

    def test_mark_inherits_unset_fields(self, layer: ProvenanceLayer):
        layer.enroll("t1", "pending")
        layer.mark("t1", token_count=500, files_written=3, iterations=4)
        latest = layer.list_records("t1")[-1]
        assert latest["channel"] == "pending", "channel should inherit"
        assert latest["token_count"] == 500
        assert latest["files_written"] == 3
        assert latest["iterations"] == 4

    def test_mark_overrides_channel(self, layer: ProvenanceLayer):
        layer.enroll("t1", "pending")
        layer.mark("t1", channel="external_tool_chain", iterations=2)
        latest = layer.list_records("t1")[-1]
        assert latest["channel"] == "external_tool_chain"

    def test_mark_invalid_channel_coerced_to_unknown(self, layer: ProvenanceLayer):
        layer.enroll("t1", "pending")
        layer.mark("t1", channel="bogus")  # type: ignore[arg-type]
        latest = layer.list_records("t1")[-1]
        assert latest["channel"] == "unknown"

    def test_mark_stores_payload_json(self, layer: ProvenanceLayer):
        layer.enroll("t1", "pending")
        layer.mark("t1", payload={"phase": "writer", "files": ["a.rs", "b.rs"]})
        latest = layer.list_records("t1")[-1]
        assert latest["payload"]["phase"] == "writer"
        assert latest["payload"]["files"] == ["a.rs", "b.rs"]


# =====================================================================
# audit — deliverable_blocked rules
# =====================================================================


class TestAuditBlockedRules:
    def test_audit_empty_task_returns_sane_defaults(self, layer: ProvenanceLayer):
        rep = layer.audit("nope")
        assert rep.execution_channel == "unknown"
        assert rep.files_written_count == 0
        assert rep.total_iterations == 0
        assert rep.deliverable_blocked is False
        assert any("No provenance records" in w for w in rep.warnings)

    def test_audit_native_channel_not_blocked_even_with_high_tokens(self, layer: ProvenanceLayer):
        layer.enroll("t1", "native_planner_loop")
        layer.mark("t1", token_count=9001, files_written=5, iterations=4)
        rep = layer.audit("t1")
        assert rep.execution_channel == "native_planner_loop"
        assert rep.deliverable_blocked is False
        assert rep.files_written_count == 5
        assert rep.total_iterations == 4

    def test_audit_unknown_small_tokens_not_blocked(self, layer: ProvenanceLayer):
        layer.enroll("t1", "unknown")
        layer.mark("t1", token_count=1000, files_written=2, iterations=1)
        rep = layer.audit("t1")
        assert rep.execution_channel == "unknown"
        assert rep.deliverable_blocked is False
        assert any("tokens=1000 <= 4000" in w for w in rep.warnings)

    def test_audit_unknown_large_tokens_is_blocked(self, layer: ProvenanceLayer):
        layer.enroll("t1", "unknown")
        layer.mark("t1", token_count=5000, files_written=3, iterations=2)
        rep = layer.audit("t1")
        assert rep.execution_channel == "unknown"
        assert rep.deliverable_blocked is True
        assert any("audit_needed" in w for w in rep.warnings)
        assert rep.files_written_count == 3
        assert rep.total_iterations == 2

    def test_audit_unknown_exactly_threshold_not_blocked(self, layer: ProvenanceLayer):
        """4000 exactly is NOT > 4000 so must not block."""
        layer.enroll("t1", "unknown")
        layer.mark("t1", token_count=4000)
        rep = layer.audit("t1")
        assert rep.deliverable_blocked is False


# =====================================================================
# AuditReport.to_dict + reset helper
# =====================================================================


class TestAuditReportAndReset:
    def test_audit_report_to_dict_keys(self, layer: ProvenanceLayer):
        layer.enroll("t1", "native_planner_loop")
        layer.mark("t1", token_count=200, files_written=1, iterations=1)
        rep = layer.audit("t1")
        d = rep.to_dict()
        for k in [
            "deliverable_blocked",
            "execution_channel",
            "files_written_count",
            "total_iterations",
            "warnings",
        ]:
            assert k in d

    def test_reset_removes_single_task(self, layer: ProvenanceLayer):
        layer.enroll("a", "pending")
        layer.enroll("b", "pending")
        layer.reset("a")
        assert layer.list_records("a") == []
        assert len(layer.list_records("b")) == 1

    def test_reset_all(self, layer: ProvenanceLayer):
        layer.enroll("a", "pending")
        layer.enroll("b", "pending")
        layer.reset()
        assert layer.list_records("a") == []
        assert layer.list_records("b") == []


# =====================================================================
# singleton get_default_layer
# =====================================================================


class TestDefaultLayerSingleton:
    def test_get_default_layer_returns_layer(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        db = tmp_path / "shared.db"
        monkeypatch.setenv("MORE_PROVENANCE_DB", str(db))
        a = get_default_layer()
        b = get_default_layer()
        assert a is b
        a.enroll("shared_t", "pending")
        rows = b.list_records("shared_t")
        assert len(rows) == 1


# =====================================================================
# API endpoint tests
# =====================================================================


class TestAuditEndpoint:
    @staticmethod
    def _wire_task_store(tmp_path: Path):
        from more_core.persistence.task_store import SQLiteTaskStore
        import more_core.api.routers.tasks as _tr
        old = _tr._task_store
        dbp = tmp_path / "api_tasks.db"
        new_store = SQLiteTaskStore(dbp)
        _tr._task_store = new_store
        return old, new_store

    def test_get_audit_not_found_returns_404_style_status(
        self, client_with_provenance, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        _, client = client_with_provenance
        old_store, _ = self._wire_task_store(tmp_path)
        try:
            resp = client.get(
                "/api/v1/tasks/does-not-exist-xyz/audit",
                headers={"Authorization": "Bearer test-key-123"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "not_found"
        finally:
            import more_core.api.routers.tasks as _tr
            _tr._task_store = old_store

    def test_get_audit_endpoint_returns_report(
        self, client_with_provenance, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        core, client = client_with_provenance
        old_store, task_store = self._wire_task_store(tmp_path)
        from datetime import datetime, timezone

        tid = "audit-api-task-001"
        task_store.create_task(
            tid,
            {
                "task_id": tid,
                "title": "Audit Test",
                "type": "code_generation",
                "description": "testing audit endpoint",
                "status": "pending",
                "progress": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        from more_core.core.guardrails.provenance_audit import ProvenanceLayer
        import more_core.core.guardrails.provenance_audit as _pa

        db = tmp_path / "prov-endpoint.db"
        layer = ProvenanceLayer(db)
        layer.enroll(tid, "native_planner_loop")
        layer.mark(tid, token_count=1200, files_written=4, iterations=3)

        orig_default = _pa._default_layer
        _pa._default_layer = layer
        try:
            resp = client.get(
                f"/api/v1/tasks/{tid}/audit",
                headers={"Authorization": "Bearer test-key-123"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "audit" in data
            assert "records" in data
            audit = data["audit"]
            assert audit["execution_channel"] == "native_planner_loop"
            assert audit["files_written_count"] == 4
            assert audit["total_iterations"] == 3
            assert audit["deliverable_blocked"] is False
        finally:
            _pa._default_layer = orig_default
            import more_core.api.routers.tasks as _tr
            _tr._task_store = old_store

    def test_get_audit_blocked_unknown_high_tokens(
        self, client_with_provenance, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        core, client = client_with_provenance
        old_store, task_store = self._wire_task_store(tmp_path)
        from datetime import datetime, timezone

        tid = "audit-blocked-002"
        task_store.create_task(
            tid,
            {
                "task_id": tid,
                "title": "Blocked Audit Test",
                "type": "nlp_task",
                "description": "testing blocked audit",
                "status": "completed",
                "progress": 100,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        from more_core.core.guardrails import provenance_audit as _pa

        db = tmp_path / "prov-blocked.db"
        layer = ProvenanceLayer(db)
        layer.enroll(tid, "unknown")
        layer.mark(tid, token_count=12000, files_written=2, iterations=5)
        orig_default = _pa._default_layer
        _pa._default_layer = layer
        try:
            resp = client.get(
                f"/api/v1/tasks/{tid}/audit",
                headers={"Authorization": "Bearer test-key-123"},
            )
            assert resp.status_code == 200
            data = resp.json()
            audit = data["audit"]
            assert audit["deliverable_blocked"] is True
            assert audit["execution_channel"] == "unknown"
        finally:
            _pa._default_layer = orig_default
            import more_core.api.routers.tasks as _tr
            _tr._task_store = old_store


# =====================================================================
# v2 executor integration smoke test — verifies provenance + task_store updates
# =====================================================================


class TestExecutorV2Integration:
    @pytest.mark.asyncio
    async def test_v2_executor_updates_task_store_fields(self, tmp_path: Path):
        from more_core.persistence.task_store import SQLiteTaskStore
        from more_core.core.config import Settings
        from more_core.runtime.orchestrator import MoRECore
        from conftest import _FakeLLMProvider
        from more_core.api.routers.tasks import _execute_task_background_v2
        from datetime import datetime, timezone

        tasks_db = tmp_path / "tstore.db"
        prov_db = tmp_path / "tprov.db"

        settings = Settings(
            providers=[],
            fallback_chain=[],
            enable_evolution=False,
            enable_metacognition=False,
            enable_symbolic=True,
        )
        core = MoRECore(settings)
        core.llm._providers["fake"] = _FakeLLMProvider()
        core.llm._fallback = ["fake"]

        store = SQLiteTaskStore(tasks_db)
        import more_core.api.routers.tasks as tr_mod

        tr_mod._task_store = store
        from more_core.core.guardrails import provenance_audit as _pa

        layer = ProvenanceLayer(prov_db)
        _pa._default_layer = layer

        tid = "v2-integ-test-001"
        store.create_task(
            tid,
            {
                "task_id": tid,
                "title": "Tetris Build",
                "type": "code_generation",
                "description": "build tetris project",
                "status": "pending",
                "progress": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        task_info = {
            "task_id": tid,
            "title": "Tetris Build",
            "description": "build tetris project",
            "type": "code_generation",
            "priority": "medium",
            "context": {"demo": True},
        }
        await _execute_task_background_v2(tid, task_info, core)

        task = store.get_task(tid)
        assert task is not None
        assert isinstance(task["artifacts"], list)
        assert len(task["artifacts"]) >= 2
        phases = {a.get("phase") for a in task["artifacts"]}
        assert "writer" in phases
        assert "validator.source" in phases or "validator" in phases
        assert "validator.archives" in phases or "delivery" in phases
        assert "delivery" in phases
        assert isinstance(task["warnings"], list)

        # V-03: 终态必须与验证结果一致——验证通过才算 completed，
        # 验证失败必须是 failed 且不得宣称 100% 完成。
        # 权威验证结果来自 aggregate artifact（executor v2 无 phase=="validator" 条目）；
        # aggregate 异常时退化为 validator.* 的最后一条，两者皆无则视为未通过。
        validator = next(
            (a for a in task["artifacts"] if a.get("phase") == "aggregate"),
            None,
        )
        if validator is None:
            v_arts = [
                a for a in task["artifacts"]
                if str(a.get("phase", "")).startswith("validator")
            ]
            validator = v_arts[-1] if v_arts else {"pass": False}
        if validator.get("pass") is True:
            assert task["status"] == "completed"
            assert task["progress"] == 100
            assert task["current_step"] == "done"
        else:
            assert task["status"] == "failed", (
                f"validation failed but task reported {task['status']!r}"
            )
            assert task["progress"] < 100
            assert task["current_step"] == "validation_failed"
            assert any("Validator hard-blocked release" in w for w in task["warnings"])

        # 未通过验证的交付物必须被溯源审计阻断
        report = layer.audit(tid)
        assert report.deliverable_blocked is (validator.get("pass") is not True)

        records = layer.list_records(tid)
        assert len(records) >= 2
        channels = {r["channel"] for r in records}
        assert "native_planner_loop" in channels
