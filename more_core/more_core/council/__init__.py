"""Multi-role cognitive council module v2 — 借鉴 ai_council 2 增强版。

Provides:
- :class:`CouncilOrchestrator`: v2 场景感知 + 模式驱动的 3-stage debate pipeline
- :class:`CouncilResult`: structured debate delivery
- Role charters: 5 core + 3 extended cognitive roles
- Confidence model: 4-dimension evidence-based scoring
- Self-check: pipeline output quality audit
- Clarification: pre-execution requirement clarification
- Consensus map: multi-layer disagreement visualization
- Validators: whitelist-cleaning schema gate
- Dispute Matrix: role-to-role conflict tracking
- Cognitive Templates: structured thinking templates for roles
- Summary Extractor: layered context compression
"""

from .clarification import (
    ClarificationResult,
    build_clarification_prompt,
    parse_clarification_response,
)
from .cognitive_templates import COGNITIVE_STYLES, CORE_TEMPLATES, inject_template
from .confidence import ConfidenceBreakdown, compute_breakdown, compute_simple_breakdown
from .consensus_map import ConsensusMap, build_consensus_map
from .dispute_matrix import DisputeMatrix
from .orchestrator import CouncilOrchestrator, CouncilResult
from .roles import InMemoryCharterProvider, RoleCharterProvider
from .self_check import SelfCheckReport, run_pipeline_self_check
from .summary_extractor import summarize_outputs, summarize_role_output
from .validators import (
    BASIC_GATE,
    STANDARD_GATE,
    STRICT_GATE,
    OutputGate,
    SchemaViolation,
    validate_json_output,
    validate_role_output,
)

__all__ = [
    "BASIC_GATE",
    "COGNITIVE_STYLES",
    "CORE_TEMPLATES",
    "STANDARD_GATE",
    "STRICT_GATE",
    "ClarificationResult",
    "ConfidenceBreakdown",
    "ConsensusMap",
    "CouncilOrchestrator",
    "CouncilResult",
    "DisputeMatrix",
    "InMemoryCharterProvider",
    "OutputGate",
    "RoleCharterProvider",
    "SchemaViolation",
    "SelfCheckReport",
    "build_clarification_prompt",
    "build_consensus_map",
    "compute_breakdown",
    "compute_simple_breakdown",
    "inject_template",
    "parse_clarification_response",
    "run_pipeline_self_check",
    "summarize_outputs",
    "summarize_role_output",
    "validate_json_output",
    "validate_role_output",
]
