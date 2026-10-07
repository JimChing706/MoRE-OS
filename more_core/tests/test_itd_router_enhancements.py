"""ITD router enhancement tests — 4 tests covering:
1. parse/validate issues[] 5-field (type/message/line/col/suggestion)
2. validate summary: requirements/kill_criteria/acceptance_criteria
3. import(auto_start=False): 1 parent + N sub tasks with parent_id / REQ-id title / pending
4. POST /tasks/itd/generate with {document: dict} returns markdown
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_INNER_ROOT = _Path(__file__).resolve().parents[1]
# repo_root/more_core directory must be first in sys.path so `import api.routers.tasks` works.
if str(_INNER_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_INNER_ROOT))

import pytest

# fastapi 为可选依赖：先 importorskip，再导入其余模块（故 E402 属预期行为）。
pytest.importorskip("fastapi")

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from more_core.api.server import create_app
from more_core.core.config import Settings
from more_core.core.import_task import (
    ImportKillCriterion,
    ImportTaskDocument,
    ImportTaskGenerator,
    Priority,
    RequirementItem,
    ResourceBudget,
)
from more_core.runtime.orchestrator import MoRECore


@pytest.fixture(autouse=True)
def _ensure_clean_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    monkeypatch.delenv("MORE_REQUIRE_API_KEY", raising=False)


@pytest.fixture
def _core():
    settings = Settings(
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
    )
    core = MoRECore(settings)
    from conftest import _FakeLLMProvider

    core.llm._providers["fake"] = _FakeLLMProvider()
    core.llm._fallback = ["fake"]
    return core


@pytest.fixture
def client(_core, monkeypatch, tmp_path):
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    monkeypatch.delenv("MORE_REQUIRE_API_KEY", raising=False)
    # Force the routers to share a single tasks.db per test.
    # Always import through top-level more_core package.
    from more_core.api.routers import import_task as _itd_mod
    from more_core.api.routers import tasks as _tasks_mod

    _tmp_db = tmp_path / "itd_test_tasks.db"
    _new_store = _tasks_mod.SQLiteTaskStore(str(_tmp_db))
    # Swap BOTH router modules so they share the same in-memory instance.
    _tasks_mod._task_store = _new_store
    _itd_mod._task_store = _new_store
    # Reset provenance singleton to per-test tmp DB
    monkeypatch.setenv("MORE_PROVENANCE_DB", str(tmp_path / "prov.db"))
    from more_core.core.guardrails import provenance_audit as _mod

    _mod._default_layer = None
    app = create_app(_core)
    with TestClient(app) as c:
        yield c


def _sample_itd_markdown() -> str:
    doc = ImportTaskDocument(
        title="Enhancement Test Task",
        version="1.0.0",
        author="test",
        created="2026-07-23T00:00:00Z",
        type="code_generation",
        priority="medium",
        deliverable_kind="code",
        tags=["test", "enhance"],
        summary="Sample task for enhancement tests",
        requirements=[
            RequirementItem(
                id="REQ-001",
                title="First feature",
                description="Implement the first feature",
                priority=Priority.HIGH,
                acceptance_criteria=["Feature works correctly", "Unit tests pass"],
            ),
            RequirementItem(
                id="REQ-002",
                title="Second feature",
                description="Implement the second feature",
                priority=Priority.MEDIUM,
                acceptance_criteria=["Feature works"],
            ),
        ],
        contract_kind="code",
        contract_required_dimensions=["core_output", "reasoning", "tests"],
        contract_acceptance_criteria=[
            "All tests pass",
            "Code coverage >= 80%",
        ],
        kill_criteria=[
            ImportKillCriterion(
                id="KC-001",
                condition="Execution timeout > 300s",
                severity="critical",
                timeline="immediate",
                fallback="Abort and report",
            )
        ],
        budget=ResourceBudget(estimated_tokens=5000, estimated_duration_min=20),
    )
    return ImportTaskGenerator().generate(doc)


def _mode_b_markdown() -> str:
    return """# Mode B Test Task

## REQ-001: First requirement
**Priority:** HIGH
**Description:** First requirement description

**Acceptance Criteria:**
- [x] Criterion one
- [x] Criterion two

## REQ-002: Second requirement
**Priority:** MEDIUM
**Description:** Second requirement description

**Acceptance Criteria:**
- [x] Criterion A
"""


class TestIssuesFiveFields:
    def test_parse_issues_have_5_fields(self, client):
        md = _mode_b_markdown()
        resp = client.post("/api/v1/tasks/itd/parse", json={"content": md})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "issues" in data
        issues = data["issues"]
        assert isinstance(issues, list) and len(issues) > 0
        for issue in issues:
            assert "type" in issue
            assert "message" in issue
            assert "line" in issue
            assert "col" in issue
            assert "suggestion" in issue
            assert isinstance(issue["line"], int)
            assert isinstance(issue["col"], int)
            assert isinstance(issue["suggestion"], str)

    def test_validate_issues_have_5_fields(self, client):
        md = _mode_b_markdown()
        resp = client.post("/api/v1/tasks/itd/validate", json={"content": md})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        issues = data["issues"]
        assert isinstance(issues, list) and len(issues) > 0
        for issue in issues:
            for field in ("type", "message", "line", "col", "suggestion"):
                assert field in issue, f"Missing field: {field}"
            assert isinstance(issue["line"], int)
            assert isinstance(issue["col"], int)


class TestValidateSummaryThreeFields:
    def test_validate_summary_has_requirements_kill_criteria_acceptance_criteria(self, client):
        md = _sample_itd_markdown()
        resp = client.post("/api/v1/tasks/itd/validate", json={"content": md})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        summary = data["summary"]
        assert "requirements" in summary
        assert "kill_criteria" in summary
        assert "acceptance_criteria" in summary

        requirements = summary["requirements"]
        kill_criteria = summary["kill_criteria"]
        acceptance_criteria = summary["acceptance_criteria"]

        assert isinstance(requirements, list)
        assert len(requirements) == 2
        assert requirements[0]["id"] == "REQ-001"
        assert requirements[1]["id"] == "REQ-002"

        assert isinstance(kill_criteria, list)
        assert len(kill_criteria) == 1
        assert kill_criteria[0]["id"] == "KC-001"
        assert kill_criteria[0]["severity"] == "critical"

        assert isinstance(acceptance_criteria, list)
        assert len(acceptance_criteria) == 2
        assert "All tests pass" in acceptance_criteria


class TestImportParentSubTasks:
    def test_import_auto_start_false_creates_parent_and_subtasks(self, client):
        md = _sample_itd_markdown()
        resp = client.post(
            "/api/v1/tasks/itd/import",
            json={"content": md, "auto_start": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        task = data["task"]
        parent_task_id = task["task_id"]
        assert task["status"] == "pending"

        # Use the *same* _task_store singleton that the routers import from
        # (guaranteed identical because the client fixture already swapped it
        # to a per-test tmp DB before create_app ran).
        from more_core.api.routers import import_task as _itd_rtr
        from more_core.api.routers import tasks as _tasks_rtr

        store1 = _tasks_rtr._task_store
        store2 = _itd_rtr._task_store
        assert store1 is store2 or str(store1._db_path) == str(store2._db_path), (
            f"store mismatch: {store1._db_path!r} vs {store2._db_path!r}"
        )
        _task_store = store1

        parent = _task_store.get_task(parent_task_id)
        assert parent is not None, (
            f"parent not found via store @ {_task_store._db_path}; "
            f"response status={data.get('status')} warnings={data.get('warnings')}"
        )
        assert parent["status"] == "pending"
        assert parent["title"] == "Enhancement Test Task"
        ctx = parent.get("context") if isinstance(parent.get("context"), dict) else {}
        assert ctx.get("parent_id") is None

        subtask_ids = task.get("subtask_ids", [])
        assert len(subtask_ids) == 2

        for i, stid in enumerate(subtask_ids, start=1):
            subtask = _task_store.get_task(stid)
            assert subtask is not None
            assert subtask["status"] == "pending"
            ctx = subtask.get("context") if isinstance(subtask.get("context"), dict) else {}
            assert ctx.get("parent_id") == parent_task_id
            expected_prefixes = (f"REQ-00{i}", "REQ-001", "REQ-002")
            assert subtask["title"].startswith(expected_prefixes)


class TestGenerateWithDocumentDict:
    def test_generate_with_document_dict_returns_markdown(self, client):
        req1 = RequirementItem(
            id="REQ-001",
            title="Doc dict requirement",
            description="From document dict",
            priority=Priority.HIGH,
            acceptance_criteria=["AC from doc dict"],
        )
        doc = ImportTaskDocument(
            title="Dict-Doc Task",
            version="2.0.0",
            author="dict-test",
            created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            type="nlp_task",
            priority="high",
            deliverable_kind="custom",
            tags=["dict", "doc"],
            summary="Task generated from a document dict",
            requirements=[req1],
            contract_kind="custom",
            contract_required_dimensions=["core_output"],
            contract_acceptance_criteria=["Output is valid markdown"],
        )
        doc_dict = doc.to_dict()
        resp = client.post(
            "/api/v1/tasks/itd/generate",
            json={"document": doc_dict},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["status"] == "success"
        md = payload["markdown"]
        assert "title: Dict-Doc Task" in md
        assert "version: 2.0.0" in md
        assert "author: dict-test" in md
        assert "priority: high" in md
        assert "REQ-001" in md
        assert "Doc dict requirement" in md
        assert "Output is valid markdown" in md
