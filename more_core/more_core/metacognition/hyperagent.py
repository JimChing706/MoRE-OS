"""HyperAgent self-modification scaffold (controlled).

This baseline records *proposals* but does not auto-apply them.  A
plugin may subscribe to the ``metacog.proposal`` event and route the
proposal through human review and sandboxed re-deployment.
"""

from __future__ import annotations

import asyncio
import json as _json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ..core.errors import MoREError
from ..governance.audit import AuditLogger

if TYPE_CHECKING:  # pragma: no cover
    from ..layers.base import LayerContext


class ProposalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ModificationType(Enum):
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"
    RENAME = "rename"


@dataclass(slots=True)
class SelfModProposal:
    id: str = field(default_factory=lambda: f"mod_{uuid.uuid4().hex[:8]}")
    target: str = ""
    target_line_start: int = 0
    target_line_end: int = 0
    modification_type: str = ModificationType.REPLACE.value
    content: str = ""
    rationale: str = ""
    original_content: str = ""
    status: str = ProposalStatus.PENDING.value
    applied_at: str = ""
    applied_by: str = ""
    rollback_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class VersionSnapshot:
    id: str = field(default_factory=lambda: f"v_{uuid.uuid4().hex[:8]}")
    file_path: str = ""
    content: str = ""
    proposal_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: str = ""


class VersionControl:
    def __init__(self, base_dir: str = "data/versions") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots: list[VersionSnapshot] = []

    def snapshot(self, file_path: str, proposal_id: str, description: str = "") -> VersionSnapshot:
        path = Path(file_path)
        if path.exists():
            content = path.read_text(encoding="utf-8")
        else:
            content = ""
        snapshot = VersionSnapshot(
            file_path=file_path,
            content=content,
            proposal_id=proposal_id,
            description=description,
        )
        self._snapshots.append(snapshot)
        self._write_snapshot(snapshot)
        return snapshot

    def _write_snapshot(self, snapshot: VersionSnapshot) -> None:
        snapshot_file = self._base_dir / f"{snapshot.id}.json"
        snapshot_file.write_text(
            _json.dumps(
                {
                    "id": snapshot.id,
                    "file_path": snapshot.file_path,
                    "proposal_id": snapshot.proposal_id,
                    "created_at": snapshot.created_at,
                    "description": snapshot.description,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        content_file = self._base_dir / f"{snapshot.id}.content"
        content_file.write_text(snapshot.content, encoding="utf-8")

    def rollback(self, snapshot_id: str) -> bool:
        for snapshot in self._snapshots:
            if snapshot.id == snapshot_id:
                path = Path(snapshot.file_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(snapshot.content, encoding="utf-8")
                return True
        return False


class SandboxValidator:
    def __init__(
        self,
        timeout_s: int = 10,
        memory_mb: int = 256,
    ) -> None:
        self._timeout = timeout_s
        self._memory = memory_mb

    async def validate(self, code: str) -> tuple[bool, str]:
        import tempfile
        from pathlib import Path

        # Use unified SandboxPolicy for import and keyword checks
        try:
            from ..sandbox.policy import default_policy

            policy = default_policy()
            safe, reason = policy.is_safe(code)
            if not safe:
                return False, reason
        except Exception:  # noqa: BLE001, S110
            # Fallback: policy unavailable (bootstrap edge-case)
            pass

        try:
            compile(code, "<hyperagent>", "exec")
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

        with tempfile.TemporaryDirectory(prefix="more_validate_") as tmp:
            script = Path(tmp) / "validate.py"
            script.write_text(code, encoding="utf-8")
            proc = await asyncio.create_subprocess_exec(
                "python3",
                "-I",
                str(script),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmp,
            )
            try:
                _out, err = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._timeout,
                )
                if proc.returncode != 0:
                    return False, err.decode("utf-8", "replace")
                return True, "Validation passed"
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return False, "Validation timeout"


class HyperAgent:
    def __init__(
        self,
        version_control: VersionControl | None = None,
        sandbox_executor: Callable[[str], bool] | None = None,
        sandbox_validator: SandboxValidator | None = None,
        audit_logger: AuditLogger | None = None,
        project_root: str | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._proposals: list[SelfModProposal] = []
        self._version_control = version_control or VersionControl()
        self._sandbox_executor = sandbox_executor
        self._sandbox_validator = sandbox_validator or SandboxValidator()
        self._audit_logger = audit_logger
        self._event_bus = event_bus
        self._project_root: Path = (
            Path(project_root).resolve() if project_root else Path.cwd().resolve()
        )
        self._allowed_targets: list[str] = [
            "more_core/layers/l4_cognition.py",
            "more_core/layers/l3_symbolic.py",
            "more_core/router/layer_router.py",
            "more_core/core/config.py",
        ]

    def register_audit_logger(self, logger: AuditLogger) -> None:
        self._audit_logger = logger

    def set_allowed_targets(self, targets: list[str]) -> None:
        validated: list[str] = []
        for t in targets:
            resolved = (self._project_root / t).resolve()
            if not str(resolved).startswith(str(self._project_root)):
                raise MoREError(f"target escapes project root: {t}")
            validated.append(t)
        self._allowed_targets = validated

    def register_sandbox_executor(self, executor: Callable[[str], bool]) -> None:
        self._sandbox_executor = executor

    def register_sandbox_validator(self, validator: SandboxValidator) -> None:
        self._sandbox_validator = validator

    def _parse_diff(self, diff: str, target: str) -> SelfModProposal | None:
        lines = diff.strip().split("\n")
        content = ""
        insert_line = 0
        delete_count = 0

        content_match = re.search(r"@@ (-?\d+),(\d+) \+(\d+),(\d+) @@", diff)
        if content_match:
            insert_line = int(content_match.group(3))
        else:
            for line in lines:
                if line.startswith("+") and not line.startswith("+++"):
                    content += line[1:] + "\n"
                elif line.startswith("-") and not line.startswith("---"):
                    delete_count += 1

        if content.strip():
            return SelfModProposal(
                target=target,
                target_line_start=insert_line,
                target_line_end=insert_line + delete_count,
                modification_type=ModificationType.REPLACE.value,
                content=content.strip(),
            )
        return None

    async def consider(
        self, ctx: LayerContext, calibration: dict[str, object]
    ) -> SelfModProposal | None:
        alignment = cast(float, calibration.get("alignment", 1.0))
        if alignment >= 0.85:
            return None

        llm_proposal = await self._llm_generate_proposal(ctx, calibration)
        if llm_proposal:
            self._proposals.append(llm_proposal)
            await self._publish_proposal(llm_proposal)
            return llm_proposal

        targets_with_low_confidence = [
            "L4.difficulty_heuristic",
            "L3.rule_weight",
            "router.fallback_order",
        ]
        selected_target = targets_with_low_confidence[0]

        proposal = SelfModProposal(
            target=selected_target,
            rationale=f"low alignment={alignment:.2f} on task={ctx.request.id}",
            content=self._generate_suggestion(selected_target, alignment),
        )
        self._proposals.append(proposal)
        await self._publish_proposal(proposal)
        return proposal

    async def _llm_generate_proposal(
        self, ctx: LayerContext, calibration: dict[str, object]
    ) -> SelfModProposal | None:
        """Use LLM to generate intelligent self-modification proposals."""
        try:
            from ..llm.provider import LLMRequest

            core = ctx.core
            if not hasattr(core, "llm") or core.llm is None:
                return None

            prompt = self._build_llm_prompt(ctx, calibration)
            llm_req = LLMRequest(
                prompt=prompt,
                system="You are HyperAgent, a self-modification system. Analyze the task execution and propose code improvements.",
                temperature=0.7,
                max_tokens=1536,
            )

            resp = await core.llm.generate(llm_req)
            return self._parse_llm_response(resp.content, ctx, calibration)

        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(f"LLM proposal generation failed: {e}")
            return None

    def _build_llm_prompt(self, ctx: LayerContext, calibration: dict[str, object]) -> str:
        steps_summary = "\n".join(
            [
                f"  {s.layer.value}: {s.description} (conf={s.confidence:.2f}, {s.duration_ms:.1f}ms)"
                for s in ctx.accumulated_steps[-5:]
            ]
        )

        return f"""Analyze the following task execution and propose a self-modification.

## Task
ID: {ctx.request.id}
Type: {ctx.request.type.value}
Query: {ctx.request.query[:200]}...

## Execution Steps (last 5)
{steps_summary}

## Calibration
Alignment: {calibration.get("alignment", 0):.2f}
Accuracy: {calibration.get("accuracy", 0):.2f}
Confidence: {calibration.get("confidence", 0):.2f}

## Scratch Data
{_json.dumps({k: str(v)[:100] for k, v in ctx.scratch.items()}, indent=2)}

## Available Targets
- more_core/layers/l4_cognition.py (difficulty scoring)
- more_core/layers/l3_symbolic.py (rule weights)
- more_core/router/layer_router.py (pipeline routing)
- more_core/core/config.py (system configuration)

Generate a self-modification proposal in JSON format:
```json
{{
  "target": "path/to/file.py",
  "modification_type": "replace|insert|delete",
  "line_start": 10,
  "line_end": 20,
  "content": "new code content",
  "rationale": "why this change improves the system"
}}
```

Output ONLY valid JSON wrapped in <proposal> tags:"""

    def _parse_llm_response(
        self, response: str, ctx: LayerContext, calibration: dict[str, object]
    ) -> SelfModProposal | None:
        import re

        match = re.search(r"<proposal>\s*(\{.*?\})\s*</proposal>", response, re.DOTALL)
        if not match and "```json" in response:
            match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)

        if not match:
            return None

        try:
            data = _json.loads(match.group(1))
            return SelfModProposal(
                target=data.get("target", "unknown"),
                target_line_start=data.get("line_start", 0),
                target_line_end=data.get("line_end", 0),
                modification_type=data.get("modification_type", "replace"),
                content=data.get("content", ""),
                rationale=data.get(
                    "rationale",
                    f"LLM-generated from alignment={calibration.get('alignment', 0):.2f}",
                ),
            )
        except _json.JSONDecodeError:
            return None

    async def _publish_proposal(self, proposal: SelfModProposal) -> None:
        if self._audit_logger:
            self._audit_logger.log(
                actor="hyperagent",
                action="self_modification_proposal",
                entity=proposal.id,
                target=proposal.target,
                rationale=proposal.rationale,
            )

        if self._event_bus is not None:
            await self._event_bus.publish(
                "metacog.proposal",
                data={
                    "id": proposal.id,
                    "target": proposal.target,
                    "rationale": proposal.rationale,
                    "status": proposal.status,
                },
                source="hyperagent",
            )

    def _generate_suggestion(self, target: str, alignment: float) -> str:
        suggestions = {
            "L4.difficulty_heuristic": f"Refine difficulty scoring for long prompts; current alignment={alignment:.2f}",
            "L3.rule_weight": "Adjust rule inference weights based on recent accuracy patterns",
            "router.fallback_order": "Reorder fallback chain based on latency measurements",
        }
        return suggestions.get(target, f"General optimization target: {target}")

    async def apply_proposal(self, proposal_id: str, dry_run: bool = False) -> tuple[bool, str]:
        proposal = self._get_proposal_by_id(proposal_id)
        if not proposal:
            return False, f"Proposal {proposal_id} not found"

        if proposal.status != ProposalStatus.APPROVED.value:
            return False, f"Proposal {proposal_id} not approved for application"

        if proposal.target not in self._allowed_targets:
            return False, f"Target {proposal.target} not in allowed targets"

        # Guard against path traversal
        resolved = (self._project_root / proposal.target).resolve()
        if not str(resolved).startswith(str(self._project_root)):
            return False, f"Target {proposal.target} escapes project root"

        if dry_run:
            return True, f"Dry run: would apply to {proposal.target}"

        self._version_control.snapshot(
            proposal.target, proposal.id, f"Before applying {proposal.id}"
        )

        if self._sandbox_executor:
            sandbox_valid = self._sandbox_executor(proposal.content)
            if not sandbox_valid:
                proposal.status = ProposalStatus.FAILED.value
                return False, "Sandbox validation failed"
        else:
            valid, msg = await self._sandbox_validator.validate(proposal.content)
            if not valid:
                proposal.status = ProposalStatus.FAILED.value
                return False, f"Sandbox validation failed: {msg}"

        success, msg = self._apply_modification(proposal)
        if success:
            proposal.status = ProposalStatus.APPLIED.value
            proposal.applied_at = datetime.now(timezone.utc).isoformat()
            proposal.applied_by = "hyperagent"
            if self._audit_logger:
                self._audit_logger.log(
                    actor="hyperagent",
                    action="self_modification_applied",
                    entity=proposal.id,
                    target=proposal.target,
                    rationale=proposal.rationale,
                )
        else:
            proposal.status = ProposalStatus.FAILED.value
            if self._audit_logger:
                self._audit_logger.log(
                    actor="hyperagent",
                    action="self_modification_failed",
                    entity=proposal.id,
                    target=proposal.target,
                    error=msg,
                )

        await self._publish_status_change(proposal)
        return success, msg

    def _apply_modification(self, proposal: SelfModProposal) -> tuple[bool, str]:
        target_path = (self._project_root / proposal.target).resolve()
        if not str(target_path).startswith(str(self._project_root)):
            return False, f"Target {proposal.target} escapes project root"
        if not target_path.exists():
            return False, f"Target file {proposal.target} not found"

        try:
            lines = target_path.read_text(encoding="utf-8").splitlines()

            if proposal.target_line_start > 0:
                start_idx = proposal.target_line_start - 1
                end_idx = (
                    proposal.target_line_end
                    if proposal.target_line_end > start_idx
                    else start_idx + 1
                )

                if proposal.modification_type == ModificationType.DELETE.value:
                    lines = lines[:start_idx] + lines[end_idx:]
                elif proposal.modification_type == ModificationType.REPLACE.value:
                    new_lines = proposal.content.splitlines()
                    lines = lines[:start_idx] + new_lines + lines[end_idx:]
                elif proposal.modification_type == ModificationType.INSERT.value:
                    new_lines = proposal.content.splitlines()
                    lines = lines[:start_idx] + new_lines + lines[start_idx:]
            else:
                if "difficulty_heuristic" in proposal.target:
                    lines = self._apply_difficulty_heuristic_change(lines, proposal.content)
                elif "rule_weight" in proposal.target:
                    lines = self._apply_rule_weight_change(lines, proposal.content)
                elif "fallback_order" in proposal.target:
                    lines = self._apply_fallback_order_change(lines, proposal.content)

            target_path.write_text("\n".join(lines), encoding="utf-8")
            return True, f"Applied modification to {proposal.target}"
        except Exception as e:  # noqa: BLE001
            return False, f"Failed to apply modification: {e!s}"

    def _apply_difficulty_heuristic_change(self, lines: list[str], content: str) -> list[str]:
        new_lines = []
        for line in lines:
            if "def calculate_difficulty" in line or "difficulty_score" in line:
                new_lines.append(content)
            else:
                new_lines.append(line)
        if not new_lines:
            new_lines = lines
        return new_lines

    def _apply_rule_weight_change(self, lines: list[str], content: str) -> list[str]:
        new_lines = []
        for line in lines:
            if "rule_weight" in line or "weight" in line:
                new_lines.append(content)
            else:
                new_lines.append(line)
        if not new_lines:
            new_lines = lines
        return new_lines

    def _apply_fallback_order_change(self, lines: list[str], content: str) -> list[str]:
        new_lines = []
        for line in lines:
            if "fallback" in line or "fallback_chain" in line:
                new_lines.append(content)
            else:
                new_lines.append(line)
        if not new_lines:
            new_lines = lines
        return new_lines

    def approve_proposal(self, proposal_id: str, approver: str = "admin") -> bool:
        proposal = self._get_proposal_by_id(proposal_id)
        if not proposal:
            return False
        proposal.status = ProposalStatus.APPROVED.value
        return True

    def reject_proposal(self, proposal_id: str, reason: str = "") -> bool:
        proposal = self._get_proposal_by_id(proposal_id)
        if not proposal:
            return False
        proposal.status = ProposalStatus.REJECTED.value
        return True

    def rollback_proposal(self, proposal_id: str) -> tuple[bool, str]:
        proposal = self._get_proposal_by_id(proposal_id)
        if not proposal:
            return False, f"Proposal {proposal_id} not found"

        if proposal.status != ProposalStatus.APPLIED.value:
            return False, f"Proposal {proposal_id} not applied"

        if not proposal.rollback_id:
            return False, f"No rollback snapshot for {proposal_id}"

        success = self._version_control.rollback(proposal.rollback_id)
        if success:
            proposal.status = ProposalStatus.ROLLED_BACK.value
        return success, "Rolled back" if success else "Rollback failed"

    def _get_proposal_by_id(self, proposal_id: str) -> SelfModProposal | None:
        for p in self._proposals:
            if p.id == proposal_id:
                return p
        return None

    async def _publish_status_change(self, proposal: SelfModProposal) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish(
                "metacog.proposal.status",
                data={
                    "id": proposal.id,
                    "target": proposal.target,
                    "status": proposal.status,
                },
                source="hyperagent",
            )

    def list_proposals(self, status_filter: str | None = None) -> list[SelfModProposal]:
        if status_filter:
            return [p for p in self._proposals if p.status == status_filter]
        return list(self._proposals)

    def get_proposal(self, proposal_id: str) -> SelfModProposal | None:
        return self._get_proposal_by_id(proposal_id)
