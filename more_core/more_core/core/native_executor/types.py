"""Native executor shared types (zero external deps, stdlib only)."""

from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Any, Literal

TaskTemplateKey = Literal["tetris", "cs_shooter", "generic"]


class ValidationBlockingLevel(str, enum.Enum):
    OFF = "off"
    WARN = "warn"
    HARD_BLOCK = "hard_block"


@dataclass
class AggregatedValidationResult:
    source: Any
    archives: Any
    blocking_level: ValidationBlockingLevel = ValidationBlockingLevel.HARD_BLOCK

    @property
    def pass_(self) -> bool:
        source_ok = bool(getattr(self.source, "pass_", False))
        if not self.archives or not getattr(self.archives, "command_results", None):
            return source_ok
        return source_ok and bool(getattr(self.archives, "pass_", False))

    @property
    def total_commands(self) -> int:
        src = int(getattr(self.source, "total_commands", 0))
        arc = int(getattr(self.archives, "total_commands", 0))
        return src + arc

    @property
    def passed_commands(self) -> int:
        src = int(getattr(self.source, "passed_commands", 0))
        arc = int(getattr(self.archives, "passed_commands", 0))
        return src + arc

    @property
    def should_block_release(self) -> bool:
        if self.blocking_level == ValidationBlockingLevel.OFF:
            return False
        if self.blocking_level == ValidationBlockingLevel.WARN:
            return False
        return not self.pass_


@dataclass
class TemplateDispatchResult:
    key: TaskTemplateKey
    plan_steps: list[Any]
    payload_map: dict[str, str]
    warnings: list[str] = field(default_factory=list)
