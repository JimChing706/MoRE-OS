"""Output Filtering — PII and sensitive data scrubbing.

Reference: OpenFang output sanitization.
Filters LLM outputs before delivery to channels to prevent
leaking PII, API keys, passwords, or internal system data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class FilterRule:
    """A rule for detecting and redacting sensitive content."""
    name: str
    pattern: re.Pattern[str]
    replacement: str = "[REDACTED]"
    enabled: bool = True


# Pre-built filter rules
_DEFAULT_RULES = [
    FilterRule(
        name="api_key",
        pattern=re.compile(r"(sk-[a-zA-Z0-9]{20,}|key-[a-zA-Z0-9]{20,})"),
        replacement="[API_KEY_REDACTED]",
    ),
    FilterRule(
        name="bearer_token",
        pattern=re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
        replacement="Bearer [TOKEN_REDACTED]",
    ),
    FilterRule(
        name="email",
        pattern=re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        replacement="[EMAIL_REDACTED]",
    ),
    FilterRule(
        name="phone_cn",
        pattern=re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
        replacement="[PHONE_REDACTED]",
    ),
    FilterRule(
        name="phone_intl",
        pattern=re.compile(r"\+\d{1,3}[-.\s]?\d{4,14}"),
        replacement="[PHONE_REDACTED]",
    ),
    FilterRule(
        name="id_card_cn",
        pattern=re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
        replacement="[ID_REDACTED]",
    ),
    FilterRule(
        name="credit_card",
        pattern=re.compile(r"(?<!\d)\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)"),
        replacement="[CARD_REDACTED]",
    ),
    FilterRule(
        name="ipv4",
        pattern=re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        replacement="[IP_REDACTED]",
    ),
    FilterRule(
        name="password_in_url",
        pattern=re.compile(r"(://[^:]+:)[^@]+(@)"),
        replacement=r"\1[PASS_REDACTED]\2",
    ),
    FilterRule(
        name="env_secret",
        pattern=re.compile(r"(?:PASSWORD|SECRET|TOKEN|KEY)\s*=\s*\S+", re.IGNORECASE),
        replacement="[ENV_SECRET_REDACTED]",
    ),
    FilterRule(
        name="private_key",
        pattern=re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE KEY-----[\s\S]*?-----END\s+(RSA\s+)?PRIVATE KEY-----"),
        replacement="[PRIVATE_KEY_REDACTED]",
    ),
]


class OutputFilter:
    """Filters sensitive data from LLM/agent outputs before delivery.

    Can be applied to:
    - Channel messages before send
    - API responses
    - Audit log entries
    - Dashboard display
    """

    def __init__(self, rules: list[FilterRule] | None = None) -> None:
        self._rules = rules if rules is not None else list(_DEFAULT_RULES)
        self._stats = {"total_filtered": 0, "by_rule": {}}

    def add_rule(self, rule: FilterRule) -> None:
        self._rules.append(rule)

    def remove_rule(self, name: str) -> None:
        self._rules = [r for r in self._rules if r.name != name]

    def filter(self, text: str) -> str:
        """Apply all enabled rules to the text."""
        result = text
        for rule in self._rules:
            if not rule.enabled:
                continue
            new_result = rule.pattern.sub(rule.replacement, result)
            if new_result != result:
                count = len(rule.pattern.findall(result))
                self._stats["total_filtered"] += count
                self._stats["by_rule"][rule.name] = (
                    self._stats["by_rule"].get(rule.name, 0) + count
                )
                result = new_result
        return result

    def scan(self, text: str) -> list[dict[str, Any]]:
        """Scan text for sensitive patterns without modifying.

        Returns list of findings.
        """
        findings = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            matches = rule.pattern.findall(text)
            if matches:
                findings.append({
                    "rule": rule.name,
                    "count": len(matches),
                })
        return findings

    def stats(self) -> dict[str, Any]:
        return {
            "total_rules": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules if r.enabled),
            "total_filtered": self._stats["total_filtered"],
            "by_rule": dict(self._stats["by_rule"]),
        }
