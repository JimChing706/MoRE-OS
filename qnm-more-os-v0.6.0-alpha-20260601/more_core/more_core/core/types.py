"""Domain-neutral core types for MoRE Agent OS.

All task types are *generic* (code, data, NL, agent orchestration, meta tasks).
No entertainment- or game-specific types are encoded here; industry-specific
task types belong in plugins.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class LayerId(str, Enum):
    L0 = "L0"  # Execution
    L1 = "L1"  # Orchestration
    L2 = "L2"  # Neural-Evolution
    L3 = "L3"  # Symbolic Reasoning
    L4 = "L4"  # Cognition
    L5 = "L5"  # Metacognition


class TaskType(str, Enum):
    """Generic, domain-neutral task categories.

    Industry packs extend the system via plugins rather than by adding
    enum values here (open/closed principle).
    """

    CODE_GENERATION = "code_generation"
    CODE_DEBUGGING = "code_debugging"
    CODE_REVIEW = "code_review"
    CODE_TESTING = "code_testing"
    MATH_REASONING = "math_reasoning"
    DATA_ANALYSIS = "data_analysis"
    NLP_TASK = "nlp_task"
    MULTI_AGENT_ORCHESTRATION = "multi_agent_orchestration"
    SELF_IMPROVEMENT = "self_improvement"
    CROSS_DOMAIN_TRANSFER = "cross_domain_transfer"
    ARCHITECTURE_DESIGN = "architecture_design"
    PLUGIN_DEFINED = "plugin_defined"  # opaque; plugin carries its own sub-type


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"  # blocked by governance


class EngineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    EVOLVING = "evolving"


class ReasoningStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    layer: LayerId
    description: str
    duration_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    confidence: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class PerformanceMetrics(BaseModel):
    total_duration_ms: float
    tokens_used: int = 0
    layer_transitions: int = 0
    self_improvement_iterations: int | None = None
    cross_domain_transfer_score: float | None = None


class TaskRequest(BaseModel):
    """Input to :meth:`MoRECore.execute`.

    ``plugin_type`` allows industry packs to carry their own sub-type without
    polluting the core enum.
    """

    id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    type: TaskType = TaskType.NLP_TASK
    plugin_type: str | None = None
    query: str
    context: dict[str, Any] = Field(default_factory=dict)
    target_layer: LayerId | None = None
    require_metacognitive_monitoring: bool = False
    allow_self_improvement: bool = False  # L2/L5 gating
    timeout_s: float = 60.0


class TaskResult(BaseModel):
    task_id: str
    layer: LayerId
    status: TaskStatus
    output: str = ""
    reasoning_chain: list[ReasoningStep] = Field(default_factory=list)
    performance: PerformanceMetrics
    calibration: dict[str, Any] | None = None
    evolution_branch: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServiceMetadata(BaseModel):
    name: str
    version: str
    provider: str
    endpoint: str | None = None
    status: EngineStatus = EngineStatus.IDLE
    capabilities: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
