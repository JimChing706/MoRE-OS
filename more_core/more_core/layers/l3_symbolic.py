"""L3 — Symbolic Reasoning Layer (ontology + forward-chaining rule engine).

Replaces the baseline ontology-only check with a genuine production rule
engine that performs forward-chaining inference.  Ontology constraints are
still checked, but the rule engine adds richer governance logic including
code safety, evolution gating, and extensible custom rules.
"""

from __future__ import annotations

from ..core.errors import GovernanceError
from ..core.types import LayerId
from ..ontology.rule_engine import (
    Fact,
    RuleEngine,
    default_governance_rules,
)
from .base import Layer, LayerContext, LayerResult


class SymbolicLayer(Layer):
    layer_id = LayerId.L3

    def __init__(self) -> None:
        super().__init__()
        self._engine = RuleEngine()
        for rule in default_governance_rules():
            self._engine.add_rule(rule)

    @property
    def rule_engine(self) -> RuleEngine:
        return self._engine

    async def process(self, ctx: LayerContext) -> LayerResult:
        # 1. Classic ontology check
        violations = await ctx.core.ontology.check(ctx.request)

        # 2. Build working-memory facts from request + pipeline scratch
        facts: list[Fact] = [
            Fact(kind="request", data={
                "query": ctx.request.query,
                "type": ctx.request.type.value,
                "allow_self_improvement": ctx.request.allow_self_improvement,
                "evolution_enabled": ctx.core.settings.enable_evolution,
            }),
        ]
        if "sandbox_result" in ctx.scratch:
            sbx = ctx.scratch["sandbox_result"]
            facts.append(Fact(kind="code_output", data={
                "code": getattr(sbx, "output", str(sbx)),
            }))

        # 3. Run forward-chaining inference
        inference = self._engine.run(facts, context={"settings": ctx.core.settings})
        all_violations = violations + inference.violations

        if all_violations and ctx.core.settings.strict_ontology:
            raise GovernanceError(f"symbolic violations: {all_violations}")

        ctx.scratch["inference_annotations"] = inference.annotations
        ctx.scratch["fired_rules"] = inference.fired_rules

        return LayerResult(
            layer=self.layer_id,
            description=(
                f"symbolic reasoning: {len(inference.fired_rules)} rules fired, "
                f"{len(all_violations)} violations"
            ),
            output={
                "violations": all_violations,
                "fired_rules": inference.fired_rules,
                "annotations": inference.annotations,
                "new_facts": len(inference.new_facts),
            },
            confidence=1.0 if not all_violations else 0.5,
        )
