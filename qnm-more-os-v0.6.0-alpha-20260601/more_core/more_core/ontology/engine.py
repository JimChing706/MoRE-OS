"""Ontology engine — pluggable rule evaluator.

The baseline checker validates structural properties of the request.
A production deployment can replace it with a Rete/NSPA-AI engine by
swapping in a subclass.
"""

from __future__ import annotations

from ..core.types import TaskRequest
from ..core.unicode_utils import semantic_length
from .aow import DEFAULT_CONSTRAINTS, OntologyConstraint


class OntologyEngine:
    def __init__(self, constraints: tuple[OntologyConstraint, ...] = DEFAULT_CONSTRAINTS) -> None:
        self._constraints = constraints

    def constraints(self) -> tuple[OntologyConstraint, ...]:
        return self._constraints

    async def check(self, request: TaskRequest) -> list[str]:
        """Return a list of rule_ids violated by *request*.

        Structural checks only; semantic constraints belong to L3 rule engine.
        """
        violations: list[str] = []
        if not request.query or semantic_length(request.query) > 16000:
            violations.append("outcome.validated")
        if request.allow_self_improvement and not request.require_metacognitive_monitoring:
            violations.append("policy.metacog_review")
        return violations
