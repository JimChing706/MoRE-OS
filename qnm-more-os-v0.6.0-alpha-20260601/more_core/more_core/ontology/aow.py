"""AOW v1.0 (Agentic Ontology of Work) entity + constraint model.

Reference: Skan AI, "Agentic Ontology of Work" (Feb 2026).  MoRE Core
only imports the conceptual schema; it does not bundle any Skan-licensed
artefacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OntologyEntity(str, Enum):
    AGENT = "Agent"
    SKILL = "Skill"
    INTENT = "Intent"
    CONTEXT = "Context"
    POLICY = "Policy"
    MEMORY = "Memory"
    CONFIDENCE = "Confidence"
    OUTCOME = "Outcome"


@dataclass(slots=True, frozen=True)
class OntologyConstraint:
    entity: OntologyEntity
    rule_id: str
    description: str
    priority: int  # 1 (advisory) — 10 (blocking)
    enforced: bool = True


DEFAULT_CONSTRAINTS: tuple[OntologyConstraint, ...] = (
    OntologyConstraint(
        entity=OntologyEntity.AGENT,
        rule_id="agent.sandboxed",
        description="All agent-generated code must execute inside a sandbox.",
        priority=10,
    ),
    OntologyConstraint(
        entity=OntologyEntity.POLICY,
        rule_id="policy.metacog_review",
        description="Metacognitive self-modification requires human review.",
        priority=9,
    ),
    OntologyConstraint(
        entity=OntologyEntity.CONFIDENCE,
        rule_id="confidence.threshold",
        description="Low-confidence outputs (<0.6) must retry or escalate.",
        priority=7,
    ),
    OntologyConstraint(
        entity=OntologyEntity.OUTCOME,
        rule_id="outcome.validated",
        description="Task outcomes must be validated against the intent.",
        priority=8,
    ),
)
