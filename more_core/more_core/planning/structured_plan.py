"""Structured Plan & Checklist — DeepSeek TUI pattern for MoRE OS.

Provides the hierarchical plan → checklist → task model used by L4 (planning)
and L5 (metacognition monitoring).

Inspired by DeepSeek TUI's plan/checklist_write/task_create pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PlanStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class ChecklistItem:
    """A single granular task — equivalent to DeepSeek TUI's checklist_write item."""

    id: str
    content: str
    status: PhaseStatus = PhaseStatus.PENDING

    def mark_in_progress(self) -> None:
        self.status = PhaseStatus.IN_PROGRESS

    def mark_completed(self) -> None:
        self.status = PhaseStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "content": self.content, "status": self.status.value}


@dataclass
class PlanPhase:
    """A high-level strategy phase — equivalent to DeepSeek TUI's update_plan step."""

    id: str
    name: str
    status: PhaseStatus = PhaseStatus.PENDING
    items: list[ChecklistItem] = field(default_factory=list)

    def add_item(self, item: ChecklistItem) -> None:
        self.items.append(item)

    @property
    def completed_count(self) -> int:
        return sum(1 for i in self.items if i.status == PhaseStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def progress_pct(self) -> float:
        if not self.items:
            return 0.0
        return self.completed_count / self.total_count * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "progress_pct": round(self.progress_pct, 1),
            "items": [i.to_dict() for i in self.items],
        }


@dataclass
class StructuredPlan:
    """Hierarchical plan with phases and checklists.

    Equivalent to DeepSeek TUI's combination of update_plan + checklist_write.
    """

    plan_id: str
    title: str = ""
    description: str = ""
    phases: list[PlanPhase] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    created_at: float = 0.0

    @property
    def overall_progress_pct(self) -> float:
        if not self.phases:
            return 0.0
        total_items = sum(p.total_count for p in self.phases)
        completed_items = sum(p.completed_count for p in self.phases)
        if total_items == 0:
            return 0.0
        return completed_items / total_items * 100

    @property
    def current_phase(self) -> PlanPhase | None:
        for phase in self.phases:
            if phase.status == PhaseStatus.IN_PROGRESS:
                return phase
        # Return first pending phase
        for phase in self.phases:
            if phase.status == PhaseStatus.PENDING:
                return phase
        return None

    def start_next_phase(self) -> PlanPhase | None:
        """Mark the next pending phase as in_progress."""
        next_phase = self.current_phase
        if next_phase and next_phase.status == PhaseStatus.PENDING:
            next_phase.status = PhaseStatus.IN_PROGRESS
        self.status = PlanStatus.IN_PROGRESS
        return next_phase

    def complete_current_phase(self) -> None:
        """Mark the current in-progress phase as completed."""
        phase = self.current_phase
        if phase and phase.status == PhaseStatus.IN_PROGRESS:
            phase.status = PhaseStatus.COMPLETED
        if all(p.status == PhaseStatus.COMPLETED for p in self.phases):
            self.status = PlanStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "progress_pct": round(self.overall_progress_pct, 1),
            "phases": [p.to_dict() for p in self.phases],
        }


def create_plan_from_subtasks(
    plan_id: str, title: str, subtasks: list[str], phases_per_subtask: int = 3
) -> StructuredPlan:
    """Convert L4 decomposition subtasks into a StructuredPlan.

    Each subtask becomes a PlanPhase, and each phase gets granular
    checklist items derived from the subtask description.

    Args:
        plan_id: Unique plan identifier.
        title: Plan title (usually the original query).
        subtasks: List of decomposed subtask descriptions.
        phases_per_subtask: Number of granular items to generate per phase.

    Returns:
        A StructuredPlan ready for L5 monitoring.
    """
    import time

    plan = StructuredPlan(
        plan_id=plan_id,
        title=title,
        created_at=time.time(),
        status=PlanStatus.PENDING,
    )

    for i, subtask in enumerate(subtasks):
        phase = PlanPhase(
            id=f"phase_{i + 1}",
            name=f"Phase {i + 1}: {subtask[:60]}{'...' if len(subtask) > 60 else ''}",
            status=PhaseStatus.PENDING,
        )
        # Generate granular checklist items
        for j in range(phases_per_subtask):
            item = ChecklistItem(
                id=f"{phase.id}_item_{j + 1}",
                content=f"Execute step {j + 1} of: {subtask[:80]}",
                status=PhaseStatus.PENDING,
            )
            phase.add_item(item)
        plan.phases.append(phase)

    return plan


def merge_plan_with_l4_output(
    plan: dict[str, Any],  # L4 decomposition output
    query: str,
) -> StructuredPlan | None:
    """Bridge L4 decomposition into structured plan format.

    Returns None if L4 didn't decompose (plan['decomposed'] is False).
    """
    if not plan or not plan.get("decomposed"):
        return None

    subtasks = plan.get("subtasks", [])
    if not subtasks:
        return None

    import hashlib
    import time

    plan_id = hashlib.sha256(query.encode()).hexdigest()[:12]
    structured = StructuredPlan(
        plan_id=plan_id,
        title=query[:80],
        description=f"Decomposed into {len(subtasks)} subtasks, difficulty={plan.get('difficulty', '?')}",
        created_at=time.time(),
        status=PlanStatus.PENDING,
    )

    for i, subtask in enumerate(subtasks):
        phase = PlanPhase(
            id=f"phase_{i}",
            name=subtask[:80],
            status=PhaseStatus.PENDING,
        )
        # Each subtask gets 2-3 granular items
        item_count = min(3, max(2, len(subtask) // 100))
        for j in range(item_count):
            phase.add_item(
                ChecklistItem(
                    id=f"phase_{i}_item_{j}",
                    content=f"[Subtask {i + 1}] Step {j + 1}/{item_count}",
                    status=PhaseStatus.PENDING,
                )
            )
        structured.phases.append(phase)

    return structured
