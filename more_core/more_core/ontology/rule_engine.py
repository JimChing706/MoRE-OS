"""Forward-chaining production rule engine for L3 symbolic reasoning.

Provides a lightweight, embeddable rule engine that supports:
- Declarative rule definitions with condition/action pairs
- Forward-chaining inference (Rete-lite)
- Priority-ordered firing
- Working memory for facts
- Conflict resolution via salience (priority)

This replaces the baseline ontology-only check with a genuine inference loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..core.unicode_utils import semantic_length


class RulePriority(int, Enum):
    CRITICAL = 100
    HIGH = 75
    NORMAL = 50
    LOW = 25
    DEFAULT = 50


@dataclass(slots=True)
class Fact:
    """A single assertion in working memory."""

    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "system"


@dataclass(slots=True)
class RuleAction:
    """Result of a rule firing."""

    type: str  # "assert" | "retract" | "modify" | "halt" | "annotate"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Rule:
    """Production rule: when *all* conditions match → execute actions."""

    name: str
    conditions: list[Callable[[list[Fact]], bool]]
    actions: list[Callable[[list[Fact], dict[str, Any]], list[RuleAction]]]
    priority: int = RulePriority.DEFAULT
    description: str = ""
    enabled: bool = True


class InferenceResult:
    """Collects everything that happened during a forward-chaining run."""

    def __init__(self) -> None:
        self.fired_rules: list[str] = []
        self.new_facts: list[Fact] = []
        self.annotations: dict[str, Any] = {}
        self.halted: bool = False
        self.violations: list[str] = []
        # Rule attribution: ``violation_rules[i]`` is the rule that produced
        # ``violations[i]``.  Lets governance telemetry count *which* rule
        # fired a violation instead of guessing from co-fired benign rules.
        self.violation_rules: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.violations and not self.halted


class RuleEngine:
    """Forward-chaining inference engine."""

    def __init__(self, max_iterations: int = 50) -> None:
        self._rules: list[Rule] = []
        self._max_iter = max_iterations

    # -- rule management ---------------------------------------------------

    def add_rule(self, rule: Rule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, name: str) -> None:
        self._rules = [r for r in self._rules if r.name != name]

    def list_rules(self) -> list[Rule]:
        return list(self._rules)

    # -- inference ---------------------------------------------------------

    def run(self, facts: list[Fact], context: dict[str, Any] | None = None) -> InferenceResult:
        """Forward-chain over *facts* until quiescence or halt."""
        ctx = context or {}
        wm = list(facts)  # working memory (mutable copy)
        result = InferenceResult()
        fired_this_run: set[str] = set()

        for _ in range(self._max_iter):
            matched = False
            for rule in self._rules:
                if not rule.enabled or rule.name in fired_this_run:
                    continue
                if all(cond(wm) for cond in rule.conditions):
                    matched = True
                    fired_this_run.add(rule.name)
                    result.fired_rules.append(rule.name)
                    for act_fn in rule.actions:
                        actions = act_fn(wm, ctx)
                        for act in actions:
                            self._apply(act, wm, result, rule_name=rule.name)
                    if result.halted:
                        return result
                    break  # restart from highest-priority rule
            if not matched:
                break
        return result

    @staticmethod
    def _apply(
        action: RuleAction,
        wm: list[Fact],
        result: InferenceResult,
        rule_name: str = "",
    ) -> None:
        if action.type == "assert":
            new_fact = Fact(
                kind=action.payload.get("kind", "derived"),
                data=action.payload.get("data", {}),
                source="rule_engine",
            )
            wm.append(new_fact)
            result.new_facts.append(new_fact)
        elif action.type == "retract":
            kind = action.payload.get("kind")
            wm[:] = [f for f in wm if f.kind != kind]
        elif action.type == "annotate":
            result.annotations.update(action.payload)
        elif action.type == "violation":
            result.violations.append(action.payload.get("message", "rule violation"))
            result.violation_rules.append(rule_name)
        elif action.type == "halt":
            result.halted = True


# ---- built-in governance rules ------------------------------------------


def _cond_long_query(facts: list[Fact]) -> bool:
    for f in facts:
        if f.kind == "request" and semantic_length(f.data.get("query", "")) > 10000:
            return True
    return False


def _act_long_query(facts: list[Fact], ctx: dict[str, Any]) -> list[RuleAction]:
    return [RuleAction(type="violation", payload={"message": "query exceeds 10 000 chars"})]


def _cond_self_improvement_without_gate(facts: list[Fact]) -> bool:
    for f in facts:
        if f.kind == "request":
            if f.data.get("allow_self_improvement") and not f.data.get("evolution_enabled"):
                return True
    return False


def _act_block_ungated_evolution(facts: list[Fact], ctx: dict[str, Any]) -> list[RuleAction]:
    return [
        RuleAction(
            type="violation",
            payload={
                "message": "self-improvement requested but evolution feature gate is off",
            },
        ),
    ]


def _cond_dangerous_code(facts: list[Fact]) -> bool:
    dangerous = re.compile(r"(os\.system|subprocess\.call|eval\(|exec\(|__import__)")
    for f in facts:
        if f.kind == "code_output" and dangerous.search(f.data.get("code", "")):
            return True
    return False


def _act_flag_dangerous(facts: list[Fact], ctx: dict[str, Any]) -> list[RuleAction]:
    return [
        RuleAction(
            type="annotate", payload={"safety_warning": "potentially dangerous code detected"}
        ),
        RuleAction(
            type="violation", payload={"message": "generated code uses dangerous primitives"}
        ),
    ]


# ---- destructive *request* detection -----------------------------------
# The pre-existing dangerous-code rule only inspects generated ``code_output``
# facts. It never looked at the *inbound request*, so a user asking the system
# to "执行 rm -rf /" slipped through governance untouched. This rule closes
# that gap with a deliberately narrow, high-precision pattern set (destructive
# filesystem / disk / fork-bomb primitives) to keep false positives low.
_DESTRUCTIVE_REQUEST_RE = re.compile(
    r"(\brm\s+(?:-{1,2}[a-z-]+\s+)*-{1,2}[a-z]*r[a-z]*f[a-z]*"  # rm -rf / rm -rfv
    r"|\brm\s+(?:-{1,2}[a-z-]+\s+)*-{1,2}[a-z]*f[a-z]*r[a-z]*"  # rm -fr / rm -rfv
    r"|\brm\s+-[rf]\s+-[rf]\b"  # rm -r -f / rm -f -r
    r"|\bmkfs(\.[a-z0-9]+)?\b"  # mkfs / mkfs.ext4
    r"|\bdd\b[^\n]*\bof=/dev/"  # dd if=... of=/dev/sdX
    r"|>\s*/dev/(sd|disk|nvme)"  # redirect over raw device
    r"|:\s*\(\s*\)\s*\{.*\}\s*;\s*:)",  # classic fork bomb
    re.IGNORECASE,
)


def _cond_destructive_request(facts: list[Fact]) -> bool:
    for f in facts:
        if f.kind == "request" and _DESTRUCTIVE_REQUEST_RE.search(f.data.get("query", "") or ""):
            return True
    return False


def _act_flag_destructive_request(facts: list[Fact], ctx: dict[str, Any]) -> list[RuleAction]:
    return [
        RuleAction(
            type="annotate",
            payload={"governance_warning": "destructive request intent detected"},
        ),
        RuleAction(
            type="violation",
            payload={
                "message": "request asks for a destructive/irreversible operation",
            },
        ),
    ]


# ---- code-review specific rules ----------------------------------------

_REVIEW_DIMENSIONS = [
    "security",
    "performance",
    "maintainability",
    "correctness",
    "style",
    "architecture",
    "testability",
    "documentation",
]


def _cond_code_review_task(facts: list[Fact]) -> bool:
    for f in facts:
        if f.kind == "request" and f.data.get("type") == "code_review":
            return True
    return False


def _act_code_review_annotate(facts: list[Fact], ctx: dict[str, Any]) -> list[RuleAction]:
    return [
        RuleAction(
            type="annotate",
            payload={
                "review_dimensions": _REVIEW_DIMENSIONS,
                "review_required": True,
                "structured_output": True,
                "checklist": [
                    {
                        "dim": "security",
                        "items": ["SQL注入检测", "XSS漏洞", "硬编码密钥", "权限校验"],
                    },
                    {
                        "dim": "performance",
                        "items": ["循环复杂度", "内存分配", "I/O阻塞", "缓存策略"],
                    },
                    {
                        "dim": "maintainability",
                        "items": ["函数长度", "模块耦合度", "命名规范", "注释覆盖"],
                    },
                ],
            },
        ),
    ]


# ---- architecture-design specific rules ---------------------------------

_ARCHITECTURE_CHECKLIST = [
    {"dim": "scalability", "items": ["水平扩展能力", "无状态设计", "数据分片策略"]},
    {"dim": "resilience", "items": ["容错机制", "熔断降级", "重试策略", "超时控制"]},
    {"dim": "observability", "items": ["日志规范", "指标采集", "链路追踪", "告警规则"]},
    {"dim": "security_boundary", "items": ["信任边界", "最小权限", "网络隔离", "密钥管理"]},
]


def _cond_architecture_design_task(facts: list[Fact]) -> bool:
    for f in facts:
        if f.kind == "request" and f.data.get("type") == "architecture_design":
            return True
    return False


def _act_architecture_design_annotate(facts: list[Fact], ctx: dict[str, Any]) -> list[RuleAction]:
    return [
        RuleAction(
            type="annotate",
            payload={
                "architecture_checklist": _ARCHITECTURE_CHECKLIST,
                "design_required": True,
                "structured_output": True,
                "artifacts_expected": [
                    "系统架构图(文字描述)",
                    "服务拆分方案",
                    "API网关设计",
                    "数据流图",
                    "部署拓扑",
                    "容错策略",
                ],
            },
        ),
    ]


def default_governance_rules() -> list[Rule]:
    """Return the built-in governance rule set."""
    return [
        Rule(
            name="query_length_limit",
            conditions=[_cond_long_query],
            actions=[_act_long_query],
            priority=RulePriority.CRITICAL,
            description="Block excessively long queries",
        ),
        Rule(
            name="ungated_self_improvement",
            conditions=[_cond_self_improvement_without_gate],
            actions=[_act_block_ungated_evolution],
            priority=RulePriority.CRITICAL,
            description="Prevent self-improvement when evolution is disabled",
        ),
        Rule(
            name="dangerous_code_detection",
            conditions=[_cond_dangerous_code],
            actions=[_act_flag_dangerous],
            priority=RulePriority.HIGH,
            description="Flag dangerous code patterns",
        ),
        Rule(
            name="destructive_request_detection",
            conditions=[_cond_destructive_request],
            actions=[_act_flag_destructive_request],
            priority=RulePriority.HIGH,
            description="Block requests that ask for destructive/irreversible operations",
        ),
        Rule(
            name="code_review_dimensions",
            conditions=[_cond_code_review_task],
            actions=[_act_code_review_annotate],
            priority=RulePriority.NORMAL,
            description="Generate code review dimensions and checklist",
        ),
        Rule(
            name="architecture_design_checklist",
            conditions=[_cond_architecture_design_task],
            actions=[_act_architecture_design_annotate],
            priority=RulePriority.NORMAL,
            description="Generate architecture design checklist and expected artifacts",
        ),
    ]
