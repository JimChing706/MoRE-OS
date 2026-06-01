"""Tests for the forward-chaining rule engine."""

import pytest

from more_core.ontology.rule_engine import (
    Fact,
    Rule,
    RuleAction,
    RuleEngine,
    RulePriority,
    default_governance_rules,
)


def _always_true(facts):
    return True


def _always_false(facts):
    return False


def _annotate_action(facts, ctx):
    return [RuleAction(type="annotate", payload={"hit": True})]


def _violation_action(facts, ctx):
    return [RuleAction(type="violation", payload={"message": "test violation"})]


def _halt_action(facts, ctx):
    return [RuleAction(type="halt")]


def test_empty_engine():
    engine = RuleEngine()
    result = engine.run([])
    assert result.ok
    assert result.fired_rules == []


def test_single_rule_fires():
    engine = RuleEngine()
    engine.add_rule(Rule(
        name="r1", conditions=[_always_true], actions=[_annotate_action],
    ))
    result = engine.run([Fact(kind="test")])
    assert "r1" in result.fired_rules
    assert result.annotations.get("hit") is True


def test_false_condition_no_fire():
    engine = RuleEngine()
    engine.add_rule(Rule(
        name="r1", conditions=[_always_false], actions=[_annotate_action],
    ))
    result = engine.run([Fact(kind="test")])
    assert result.fired_rules == []


def test_violation_recorded():
    engine = RuleEngine()
    engine.add_rule(Rule(
        name="v1", conditions=[_always_true], actions=[_violation_action],
    ))
    result = engine.run([Fact(kind="test")])
    assert not result.ok
    assert "test violation" in result.violations


def test_halt_stops_engine():
    engine = RuleEngine()
    engine.add_rule(Rule(
        name="halt_rule", conditions=[_always_true], actions=[_halt_action],
        priority=RulePriority.CRITICAL,
    ))
    engine.add_rule(Rule(
        name="never_reached", conditions=[_always_true], actions=[_annotate_action],
        priority=RulePriority.LOW,
    ))
    result = engine.run([Fact(kind="test")])
    assert result.halted
    assert "halt_rule" in result.fired_rules
    assert "never_reached" not in result.fired_rules


def test_priority_ordering():
    engine = RuleEngine()
    fired = []

    def mk_action(name):
        def action(facts, ctx):
            fired.append(name)
            return []
        return action

    engine.add_rule(Rule(name="low", conditions=[_always_true], actions=[mk_action("low")], priority=25))
    engine.add_rule(Rule(name="high", conditions=[_always_true], actions=[mk_action("high")], priority=75))
    engine.run([Fact(kind="test")])
    assert fired[0] == "high"


def test_default_governance_rules_exist():
    rules = default_governance_rules()
    names = {r.name for r in rules}
    assert "query_length_limit" in names
    assert "ungated_self_improvement" in names
    assert "dangerous_code_detection" in names


def test_long_query_violation():
    engine = RuleEngine()
    for r in default_governance_rules():
        engine.add_rule(r)
    facts = [Fact(kind="request", data={"query": "x" * 15000})]
    result = engine.run(facts)
    assert not result.ok
    assert any("10 000" in v for v in result.violations)


def test_ungated_evolution_violation():
    engine = RuleEngine()
    for r in default_governance_rules():
        engine.add_rule(r)
    facts = [Fact(kind="request", data={
        "query": "improve", "allow_self_improvement": True, "evolution_enabled": False,
    })]
    result = engine.run(facts)
    assert not result.ok
