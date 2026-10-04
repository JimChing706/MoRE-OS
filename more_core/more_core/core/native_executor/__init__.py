"""原生执行器子包：Planner（规划）、Writer（写入）、Validator（验证）、Delivery（交付）。

全部零新增第三方依赖，仅使用 Python 标准库与 more_core 内部已存在类型。
"""

from .types import (
    TaskTemplateKey,
    ValidationBlockingLevel,
    AggregatedValidationResult,
    TemplateDispatchResult,
)
from .planner import Planner, Step, RULE_BASED_TETRIS_PLAN, TaskTemplateSelector
from .writer import Writer, ProvenanceViolation, TaskPayloadTemplateRegistry
from .validator import Validator, ValidationResult
from .delivery import Delivery, DeliveryArtifact
from .dispatcher import TemplateDispatcher
from .payload_mixins import (
    PayloadWriterMixin,
    TetrisWriterMixin,
    CSShooterWriterMixin,
    GenericWriterMixin,
)

__all__ = [
    "AggregatedValidationResult",
    "CSShooterWriterMixin",
    "Delivery",
    "DeliveryArtifact",
    "GenericWriterMixin",
    "PayloadWriterMixin",
    "Planner",
    "ProvenanceViolation",
    "RULE_BASED_TETRIS_PLAN",
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
