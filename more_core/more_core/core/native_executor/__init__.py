"""原生执行器子包：Planner（规划）、Writer（写入）、Validator（验证）、Delivery（交付）。

全部零新增第三方依赖，仅使用 Python 标准库与 more_core 内部已存在类型。
"""

from .delivery import Delivery, DeliveryArtifact
from .dispatcher import TemplateDispatcher
from .payload_mixins import (
    CSShooterWriterMixin,
    GenericWriterMixin,
    PayloadWriterMixin,
    TetrisWriterMixin,
)
from .planner import RULE_BASED_TETRIS_PLAN, Planner, Step, TaskTemplateSelector
from .types import (
    AggregatedValidationResult,
    TaskTemplateKey,
    TemplateDispatchResult,
    ValidationBlockingLevel,
)
from .validator import ValidationResult, Validator
from .writer import ProvenanceViolation, TaskPayloadTemplateRegistry, Writer

__all__ = [
    "RULE_BASED_TETRIS_PLAN",
    "AggregatedValidationResult",
    "CSShooterWriterMixin",
    "Delivery",
    "DeliveryArtifact",
    "GenericWriterMixin",
    "PayloadWriterMixin",
    "Planner",
    "ProvenanceViolation",
    "Step",
    "TaskPayloadTemplateRegistry",
    "TaskTemplateKey",
    "TaskTemplateSelector",
    "TemplateDispatchResult",
    "TemplateDispatcher",
    "TetrisWriterMixin",
    "ValidationBlockingLevel",
    "ValidationResult",
    "Validator",
    "Writer",
]
