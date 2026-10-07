"""ITD end-to-end integration tests — ITD → TaskRequest → MoRECore.execute()."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from more_core.core.config import Settings
from more_core.core.import_task import (
    ImportKillCriterion,
    ImportTaskDocument,
    ImportTaskGenerator,
    ImportTaskParser,
    Priority,
    RequirementItem,
    ResourceBudget,
)
from more_core.core.types import LayerId, TaskRequest, TaskStatus
from more_core.layers.base import LayerResult
from more_core.router.layer_router import RoutingDecision


# ---------------------------------------------------------------------------
# Helpers — mini bootstrap from test_orchestrator.py
# ---------------------------------------------------------------------------


def _make_core(**attrs: Any) -> Any:
    from more_core.runtime.orchestrator import MoRECore

    settings = Settings(
        plugin_dir="tests/plugins",
        log_dir="tests/logs",
        providers=[],
        fallback_chain=[],
    )
    with (
        patch("more_core.runtime.orchestrator.init_capabilities") as mc,
        patch("more_core.runtime.orchestrator.init_layers") as ml,
        patch("more_core.runtime.orchestrator.init_services") as ms,
    ):
        mc.return_value = {
            "llm": MagicMock(),
            "task_model_router": MagicMock(),
            "sandbox": MagicMock(),
            "memory": MagicMock(),
            "ontology": MagicMock(),
            "metacognition": MagicMock(),
            "evolution_archive": MagicMock(),
            "evolution": MagicMock(),
            "tools": MagicMock(),
            "meta_orchestrator": None,
            "dynamic_guardrails": None,
        }
        ml.return_value = {
            "router": MagicMock(),
            "layers": {},
            "audit": MagicMock(),
            "policy": MagicMock(),
        }
        ms.return_value = {
            "channels": MagicMock(),
            "cron": MagicMock(),
            "skill_manager": MagicMock(),
            "hand_registry": MagicMock(),
            "hands": MagicMock(),
            "commands": MagicMock(),
            "plugins": MagicMock(),
            "rbac": MagicMock(),
            "taint_tracker": MagicMock(),
            "output_filter": MagicMock(),
            "reconnect_manager": MagicMock(),
            "hand_persistence": MagicMock(),
            "hand_cloner": MagicMock(),
            "planner": MagicMock(),
            "token_predictor": MagicMock(),
            "workflows": MagicMock(),
            "plan_bridge": MagicMock(),
            "plan_monitor": MagicMock(),
            "deployment_manager": MagicMock(),
            "session_manager": MagicMock(),
            "rate_limiter": MagicMock(),
            "request_cache": MagicMock(),
            "llm_circuit_breaker": MagicMock(),
        }
        core = MoRECore(settings)
    for k, v in attrs.items():
        setattr(core, k, v)
    return core


def _execute_core() -> Any:
    core = _make_core()
    core._rate_limiter.acquire = AsyncMock(return_value=True)
    core._request_cache.get = AsyncMock(return_value=None)
    core._request_cache.set = AsyncMock()
    core.router.route = MagicMock(
        return_value=RoutingDecision(pipeline=[LayerId.L0], reasoning="direct"),
    )
    core.llm.list_providers = MagicMock(return_value=["fake"])
    core.event_bus.publish = AsyncMock()
    core.audit.log = MagicMock()
    core.policy.check = MagicMock()
    core.output_filter.filter = MagicMock(side_effect=lambda x: x)

    taint_scope = MagicMock()
    taint_scope.track = MagicMock()
    taint_scope.sanitize = MagicMock()
    taint_scope.check = MagicMock(return_value=True)
    taint_scope.cleanup = MagicMock()
    core.taint_tracker.scope = MagicMock(return_value=taint_scope)

    mock_layer = MagicMock()
    mock_layer.layer_id = LayerId.L0
    mock_layer.run = AsyncMock(
        return_value=LayerResult(
            layer=LayerId.L0,
            description="L0 done",
            output="e2e-test-output",
        ),
    )
    core.layers = {LayerId.L0: mock_layer}
    return core


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_itd_document() -> ImportTaskDocument:
    return ImportTaskDocument(
        title="E2E Test Task",
        version="1.0.0",
        author="test",
        created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        type="code_generation",
        priority="high",
        deliverable_kind="code",
        tags=["e2e", "test"],
        summary="End-to-end integration test task",
        requirements=[
            RequirementItem(
                id="REQ-001",
                title="Feature X",
                description="Implement feature X",
                priority=Priority.HIGH,
                acceptance_criteria=["AC1: feature works", "AC2: tests pass"],
            ),
        ],
        contract_kind="code",
        contract_required_dimensions=["core_output", "reasoning"],
        contract_acceptance_criteria=["Output must be valid"],
        kill_criteria=[
            ImportKillCriterion(
                id="KC-001",
                condition="Tests fail",
                severity="critical",
                timeline="immediate",
                fallback="Stop and report",
            ),
        ],
        budget=ResourceBudget(
            estimated_tokens=1000,
            estimated_duration_min=5,
            max_iterations=3,
        ),
        context_background="Testing background context",
        context_constraints=["Must not use external APIs"],
        context_references=["docs/test.md"],
        related_documents=["ADR-001"],
    )


@pytest.fixture
def sample_itd_markdown(sample_itd_document: ImportTaskDocument) -> str:
    return ImportTaskGenerator().generate(sample_itd_document)


@pytest.fixture
def core() -> Any:
    return _execute_core()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestItdE2E:
    """ITD → TaskRequest → MoRECore.execute() full pipeline."""

    @pytest.mark.asyncio
    async def test_parse_to_execute_full_pipeline(
        self,
        sample_itd_markdown: str,
        core: Any,
    ) -> None:
        """Generate ITD → parse → to_task_request → execute → validate result."""
        parser = ImportTaskParser()
        doc = parser.parse(sample_itd_markdown)

        assert doc.title == "E2E Test Task"
        assert len(doc.requirements) == 1
        assert doc.requirements[0].id == "REQ-001"

        req = doc.to_task_request()
        assert isinstance(req, TaskRequest)
        assert req.type.value == "code_generation"
        assert req.query == "End-to-end integration test task"

        result = await core.execute(req)
        assert result.status in (TaskStatus.SUCCESS, TaskStatus.PARTIAL)
        assert "e2e-test-output" in result.output
        assert result.task_id is not None
        assert len(result.deliverable_missing or []) > 0  # contract checked

    @pytest.mark.asyncio
    async def test_itd_generate_parse_roundtrip(
        self,
        sample_itd_document: ImportTaskDocument,
    ) -> None:
        """Generate ITD → parse → verify all fields survive round-trip."""
        gen = ImportTaskGenerator()
        markdown = gen.generate(sample_itd_document)

        parser = ImportTaskParser()
        doc = parser.parse(markdown)

        assert doc.title == sample_itd_document.title
        assert doc.version == sample_itd_document.version
        assert doc.type == sample_itd_document.type
        assert doc.priority == sample_itd_document.priority
        assert doc.summary == sample_itd_document.summary
        assert len(doc.requirements) == len(sample_itd_document.requirements)
        assert len(doc.kill_criteria) == len(sample_itd_document.kill_criteria)

    @pytest.mark.asyncio
    async def test_itd_parse_with_no_requirements_still_converts(
        self,
        core: Any,
    ) -> None:
        """ITD with no requirements should still generate a valid TaskRequest."""
        doc = ImportTaskDocument(
            title="Minimal Task",
            version="1.0.0",
            author="test",
            created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            type="nlp_task",
            priority="low",
            deliverable_kind="code",
            tags=[],
            summary="A minimal task without requirements",
        )
        req = doc.to_task_request()
        assert req is not None

        result = await core.execute(req)
        assert result.status == TaskStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_itd_execute_with_deliverable_contract(
        self,
        sample_itd_document: ImportTaskDocument,
        core: Any,
    ) -> None:
        """ITD contract dimensions pass through to TaskResult."""
        req = sample_itd_document.to_task_request()
        assert req.deliverable_kind == "code"

        result = await core.execute(req)
        assert result.status in (TaskStatus.SUCCESS, TaskStatus.PARTIAL)
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_itd_kill_criteria_pass_through(
        self,
        sample_itd_document: ImportTaskDocument,
    ) -> None:
        """Kill criteria should be encoded in the TaskRequest expectation."""
        req = sample_itd_document.to_task_request()
        assert req.expectation is not None
        assert "kill_criteria" in req.expectation
        assert len(req.expectation["kill_criteria"]) == 1
        assert req.expectation["kill_criteria"][0]["condition"] == "Tests fail"

    @pytest.mark.asyncio
    async def test_itd_execute_rejected_by_rate_limiter(self) -> None:
        """Rate-limited ITD execution returns REJECTED status."""
        core = _execute_core()
        core._rate_limiter.acquire = AsyncMock(return_value=False)

        doc = ImportTaskDocument(
            title="Rate Limited",
            version="1.0.0",
            author="test",
            created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            type="code_generation",
            priority="medium",
            deliverable_kind="code",
            tags=[],
            summary="Will be rate limited",
        )
        req = doc.to_task_request()
        result = await core.execute(req)
        assert result.status == TaskStatus.REJECTED
