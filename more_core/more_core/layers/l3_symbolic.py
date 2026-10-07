"""L3 — Symbolic Reasoning Layer (governance rules + symbolic mathematics).

Two-phase reasoning:
1. **Governance phase**: ontology check + forward-chaining rule engine
   (code safety, query length limits, review checklists, etc.)
2. **Symbolic phase** (MATH_REASONING tasks only): SymPy-based symbolic
   computation (equation solving, calculus, simplification, etc.)
   Results flow to L0 via ``scratch["inference_annotations"]`` and
   ``scratch["symbolic_result"]``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.errors import GovernanceError
from ..core.types import LayerId, TaskType
from ..ontology.rule_engine import (
    Fact,
    RuleEngine,
    default_governance_rules,
)
from ..ontology.symbolic_engine import SymbolicEngine, SymbolicResult
from .base import Layer, LayerContext, LayerResult

_log = logging.getLogger(__name__)


class SymbolicLayer(Layer):
    layer_id = LayerId.L3

    def __init__(self) -> None:
        super().__init__()
        self._engine = RuleEngine()
        for rule in default_governance_rules():
            self._engine.add_rule(rule)
        self._symbolic = SymbolicEngine()

    @property
    def rule_engine(self) -> RuleEngine:
        return self._engine

    @property
    def symbolic_engine(self) -> SymbolicEngine:
        return self._symbolic

    def _record_governance_event(
        self, ctx: LayerContext, inference: Any, all_violations: list[str]
    ) -> None:
        """Emit one governance evaluation row (pass or block). Never raises.

        Recording passes as well as blocks gives the "治理拦截率" metric a
        self-contained denominator (``blocked / evaluations``).
        """
        try:
            from ..governance import observability as _obs

            strict = bool(ctx.core.settings.strict_ontology)
            rules = list(getattr(inference, "violation_rules", []) or [])
            if not rules and all_violations:
                rules = list(inference.fired_rules)
            _obs.record_governance_event(
                request_id=ctx.request.id,
                layer=self.layer_id.value,
                task_type=ctx.request.type.value,
                blocked=bool(all_violations) and strict,
                strict=strict,
                rules=rules,
                violations=all_violations,
            )
        except Exception:  # pragma: no cover - telemetry must never break L3  # noqa: BLE001, S110
            pass

    async def process(self, ctx: LayerContext) -> LayerResult:
        # 1. Classic ontology check
        violations = await ctx.core.ontology.check(ctx.request)

        # 2. Build working-memory facts from request + pipeline scratch
        facts: list[Fact] = [
            Fact(
                kind="request",
                data={
                    "query": ctx.request.query,
                    "type": ctx.request.type.value,
                    "allow_self_improvement": ctx.request.allow_self_improvement,
                    "evolution_enabled": ctx.core.settings.enable_evolution,
                },
            ),
        ]
        if "sandbox_result" in ctx.scratch:
            sbx = ctx.scratch["sandbox_result"]
            facts.append(
                Fact(
                    kind="code_output",
                    data={
                        "code": getattr(sbx, "output", str(sbx)),
                    },
                )
            )

        # 3. Run forward-chaining inference (governance rules)
        inference = self._engine.run(facts, context={"settings": ctx.core.settings})
        all_violations = violations + inference.violations
        self._record_governance_event(ctx, inference, all_violations)

        if all_violations and ctx.core.settings.strict_ontology:
            raise GovernanceError(f"symbolic violations: {all_violations}")

        # 4. Symbolic mathematics phase (MATH_REASONING only)
        symbolic_result: SymbolicResult | None = None
        if ctx.request.type == TaskType.MATH_REASONING:
            symbolic_result = self._symbolic.analyse(ctx.request.query)
            if symbolic_result.success:
                ctx.scratch["symbolic_result"] = symbolic_result
                inference.annotations["symbolic_math"] = symbolic_result.result
                if symbolic_result.steps:
                    inference.annotations["symbolic_steps"] = symbolic_result.steps
            else:
                _log.warning(
                    "symbolic analysis failed for task %s: %s",
                    ctx.request.id,
                    symbolic_result.error,
                )
                inference.annotations["symbolic_error"] = symbolic_result.error

        ctx.scratch["inference_annotations"] = inference.annotations
        ctx.scratch["fired_rules"] = inference.fired_rules

        # Build description
        desc_parts = [
            f"governance: {len(inference.fired_rules)} rules, {len(all_violations)} violations",
        ]
        if symbolic_result is not None:
            if symbolic_result.success:
                desc_parts.append("symbolic math: OK")
            else:
                desc_parts.append("symbolic math: failed")

        return LayerResult(
            layer=self.layer_id,
            description=" | ".join(desc_parts),
            output={
                "violations": all_violations,
                "fired_rules": inference.fired_rules,
                "annotations": inference.annotations,
                "new_facts": len(inference.new_facts),
                "symbolic_success": symbolic_result.success if symbolic_result else None,
                "symbolic_result": str(symbolic_result.result)
                if symbolic_result and symbolic_result.success
                else None,
                "symbolic_error": symbolic_result.error
                if symbolic_result and not symbolic_result.success
                else None,
            },
            confidence=1.0 if not all_violations else 0.5,
        )
