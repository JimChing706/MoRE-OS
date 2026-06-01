"""Test HyperAgent self-modification capabilities."""

import asyncio
import pytest

from more_core.metacognition import HyperAgent, VersionControl
from more_core.metacognition.hyperagent import (
    ProposalStatus,
    SandboxValidator,
)
from more_core.governance.audit import AuditLogger, AuditRecord


@pytest.fixture
def temp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def version_control(temp_dir):
    return VersionControl(base_dir=f"{temp_dir}/versions")


@pytest.fixture
def hyperagent(version_control):
    return HyperAgent(version_control=version_control)


@pytest.fixture
def sandbox_validator():
    return SandboxValidator(timeout_s=5)


@pytest.fixture
def audit_logger(temp_dir):
    return AuditLogger(path=f"{temp_dir}/audit.jsonl")


class TestVersionControl:
    def test_snapshot_creates_files(self, version_control, temp_dir):
        test_file = f"{temp_dir}/test_module.py"
        with open(test_file, "w") as f:
            f.write("x = 1")

        snapshot = version_control.snapshot(test_file, "proposal_1", "test")
        assert snapshot.id.startswith("v_")
        assert snapshot.content == "x = 1"

    def test_rollback_restores_content(self, version_control, temp_dir):
        test_file = f"{temp_dir}/test_module.py"
        with open(test_file, "w") as f:
            f.write("x = 1")

        snapshot = version_control.snapshot(test_file, "proposal_1", "test")
        with open(test_file, "w") as f:
            f.write("x = 2")

        version_control.rollback(snapshot.id)
        with open(test_file) as f:
            assert f.read() == "x = 1"


class TestSandboxValidator:
    @pytest.mark.asyncio
    async def test_validate_safe_code(self, sandbox_validator):
        code = "import math\nresult = math.sqrt(16)\nprint(result)"
        valid, msg = await sandbox_validator.validate(code)
        assert valid is True

    @pytest.mark.asyncio
    async def test_reject_dangerous_import(self, sandbox_validator):
        code = "import os\nos.system('rm -rf /')"
        valid, msg = await sandbox_validator.validate(code)
        assert valid is False
        assert "Disallowed import" in msg

    @pytest.mark.asyncio
    async def test_reject_syntax_error(self, sandbox_validator):
        code = "def broken("
        valid, msg = await sandbox_validator.validate(code)
        assert valid is False
        assert "Syntax error" in msg


class TestHyperAgent:
    @pytest.mark.asyncio
    async def test_proposal_status_transitions(self, hyperagent):
        from more_core.layers.base import LayerContext
        from more_core.core.types import TaskRequest, TaskType, ReasoningStep
        from unittest.mock import MagicMock, AsyncMock

        mock_core = MagicMock()
        mock_core.event_bus = MagicMock()
        mock_core.event_bus.publish = AsyncMock()

        mock_request = TaskRequest(type=TaskType.NLP_TASK, query="test")
        ctx = LayerContext(core=mock_core, request=mock_request)

        calibration = {"alignment": 0.5}

        proposal = await hyperagent.consider(ctx, calibration)
        assert proposal is not None
        assert proposal.status == ProposalStatus.PENDING.value

        hyperagent.approve_proposal(proposal.id, "test_admin")
        assert hyperagent.get_proposal(proposal.id).status == ProposalStatus.APPROVED.value

        hyperagent.reject_proposal("mod_nonexistent")
        assert hyperagent.get_proposal("mod_nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_proposals_with_filter(self, hyperagent):
        from more_core.layers.base import LayerContext
        from more_core.core.types import TaskRequest, TaskType
        from unittest.mock import MagicMock, AsyncMock

        mock_core = MagicMock()
        mock_core.event_bus = MagicMock()
        mock_core.event_bus.publish = AsyncMock()

        mock_request = TaskRequest(type=TaskType.NLP_TASK, query="test")
        ctx = LayerContext(core=mock_core, request=mock_request)

        calibration = {"alignment": 0.5}
        await hyperagent.consider(ctx, calibration)

        pending = hyperagent.list_proposals(status_filter="pending")
        assert len(pending) == 1

        applied = hyperagent.list_proposals(status_filter="applied")
        assert len(applied) == 0

    def test_allowed_targets_configurable(self, hyperagent):
        new_targets = ["custom/module.py", "another/module.py"]
        hyperagent.set_allowed_targets(new_targets)
        assert hyperagent._allowed_targets == new_targets


class TestHyperAgentWithAudit:
    @pytest.mark.asyncio
    async def test_audit_logger_records_proposal(self, hyperagent, audit_logger, temp_dir):
        hyperagent.register_audit_logger(audit_logger)

        from more_core.layers.base import LayerContext
        from more_core.core.types import TaskRequest, TaskType
        from unittest.mock import MagicMock, AsyncMock

        mock_core = MagicMock()
        mock_core.event_bus = MagicMock()
        mock_core.event_bus.publish = AsyncMock()

        mock_request = TaskRequest(type=TaskType.NLP_TASK, query="test")
        ctx = LayerContext(core=mock_core, request=mock_request)

        calibration = {"alignment": 0.5}
        proposal = await hyperagent.consider(ctx, calibration)

        log_file = f"{temp_dir}/audit.jsonl"
        with open(log_file) as f:
            content = f.read()
            assert "self_modification_proposal" in content
            assert proposal.id in content