"""Tests for ZEN_RULES system."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from more_core.zen_rules import (
    ZENRule,
    ZENRulesEnforcer,
    RuleSeverity,
    RuleCategory,
    ViolationRecord,
)


class TestZENRule:
    """Test suite for ZENRule."""

    def test_rule_creation(self):
        """Test creating a ZEN rule."""
        rule = ZENRule(
            id="ZEN-TEST-01",
            name="Test Rule",
            category=RuleCategory.SAFETY,
            severity=RuleSeverity.P1_CRITICAL,
            description="A test rule",
            check_fn=lambda ctx: True,
        )
        assert rule.id == "ZEN-TEST-01"
        assert rule.name == "Test Rule"

    def test_rule_with_check_fn(self):
        """Test rule with check function."""
        rule = ZENRule(
            id="ZEN-TEST-02",
            name="Evaluation Test",
            category=RuleCategory.SAFETY,
            severity=RuleSeverity.P3_MINOR,
            description="Test evaluation",
            check_fn=lambda ctx: ctx.get("value", 0) > 10,
        )
        assert rule.check_fn({"value": 20}) is True
        assert rule.check_fn({"value": 5}) is False


class TestZENRulesEnforcer:
    """Test suite for ZENRulesEnforcer."""

    def test_enforcer_singleton(self):
        """Test enforcer is a singleton."""
        # Reset singleton for testing
        ZENRulesEnforcer._instance = None
        enforcer1 = ZENRulesEnforcer()
        enforcer2 = ZENRulesEnforcer()
        assert enforcer1 is enforcer2

    def test_enforcer_initialization(self):
        """Test enforcer initializes correctly."""
        ZENRulesEnforcer._instance = None
        enforcer = ZENRulesEnforcer()
        assert enforcer is not None
        assert hasattr(enforcer, "_rules")

    def test_default_rules_registered(self):
        """Test default rules are registered."""
        ZENRulesEnforcer._instance = None
        enforcer = ZENRulesEnforcer()
        assert len(enforcer._rules) >= 15

    def test_get_rule(self):
        """Test getting a specific rule."""
        ZENRulesEnforcer._instance = None
        enforcer = ZENRulesEnforcer()
        rule = enforcer._rules.get("ZEN-01")
        assert rule is not None

    def test_check_violation(self):
        """Test checking for violations."""
        ZENRulesEnforcer._instance = None
        enforcer = ZENRulesEnforcer()

        # Test with rule that has check_fn
        rule = ZENRule(
            id="ZEN-TEST-VIOLATION",
            name="Test Violation",
            category=RuleCategory.SAFETY,
            severity=RuleSeverity.P3_MINOR,
            description="Test",
            check_fn=lambda ctx: ctx.get("allowed", True),
        )
        enforcer._rules["ZEN-TEST-VIOLATION"] = rule

        # Should not violate when allowed=True
        is_violation = enforcer.check_violation("ZEN-TEST-VIOLATION", {"allowed": True})
        assert is_violation is False

        # Should violate when allowed=False
        is_violation = enforcer.check_violation("ZEN-TEST-VIOLATION", {"allowed": False})
        assert is_violation is True

    def test_register_callback(self):
        """Test registering callback for severity."""
        ZENRulesEnforcer._instance = None
        enforcer = ZENRulesEnforcer()

        callback_called = []

        def test_callback(violation):
            callback_called.append(violation)

        enforcer.register_callback(RuleSeverity.P1_CRITICAL, test_callback)
        assert len(enforcer._callbacks[RuleSeverity.P1_CRITICAL]) > 0


class TestViolationRecord:
    """Test suite for ViolationRecord."""

    def test_violation_creation(self):
        """Test creating a violation record."""
        violation = ViolationRecord(
            rule_id="ZEN-01",
            rule_name="Test Rule",
            severity=RuleSeverity.P1_CRITICAL,
            category=RuleCategory.SAFETY,
            timestamp=1234567890.0,
            context={"test": "data"},
        )
        assert violation.rule_id == "ZEN-01"
        assert violation.resolved is False


class TestRuleSeverity:
    """Test suite for RuleSeverity."""

    def test_severity_levels(self):
        """Test all severity levels exist."""
        assert RuleSeverity.P0_FATAL.value == "p0_fatal"
        assert RuleSeverity.P1_CRITICAL.value == "p1_critical"
        assert RuleSeverity.P2_MAJOR.value == "p2_major"
        assert RuleSeverity.P3_MINOR.value == "p3_minor"


class TestRuleCategory:
    """Test suite for RuleCategory."""

    def test_category_values(self):
        """Test all categories exist."""
        assert RuleCategory.SAFETY.value == "safety"
        assert RuleCategory.SIMPLICITY.value == "simplicity"
        assert RuleCategory.CONTROL.value == "control"
        assert RuleCategory.TRACEABLE.value == "traceable"
        assert RuleCategory.EVOLUTION.value == "evolution"
        assert RuleCategory.LLM_SPECIFIC.value == "llm"
        assert RuleCategory.PROHIBITION.value == "prohibition"
