"""MoRE v3.0 — Risk-Decision Operating System enhancements.

Phase 1: Meta-Orchestrator + Dynamic Guardrails
Phase 2: SOUL Personality Profiles + Silver Habits Engineering
"""

from .dynamic_guardrails import (
    DynamicGuardrails,
    GuardrailConfig,
    SandboxLevel,
    get_dynamic_guardrails,
    reset_dynamic_guardrails,
)
from .meta_orchestrator import MetaOrchestrator, MetaRoutingDecision, RoutingMode
from .silver_habits import (
    CalibratedOutput,
    ChaosInjector,
    CircuitBreakerState,
    CollaborationBonus,
    ConvergenceDetector,
    ConvergenceSignal,
    ExpertDiversifier,
    InfoCostBenefit,
    TiltDetector,
)
from .soul_profile import (
    ARCHETYPE_DIPLOMAT,
    ARCHETYPE_ENGINEER,
    ARCHETYPE_INNOVATOR,
    ARCHETYPE_RISK_ANALYST,
    CollaborationPreference,
    ConfidenceStyle,
    DecisionStyle,
    RecoveryStyle,
    SilverHabit,
    SoulProfile,
    get_archetype,
    list_archetypes,
    register_archetype,
)
from .uncertainty import UncertaintyAssessment, UncertaintyAssessor

__all__ = [
    "ARCHETYPE_DIPLOMAT",
    "ARCHETYPE_ENGINEER",
    "ARCHETYPE_INNOVATOR",
    "ARCHETYPE_RISK_ANALYST",
    # Phase 2 — Silver Habits
    "CalibratedOutput",
    "ChaosInjector",
    "CircuitBreakerState",
    "CollaborationBonus",
    "CollaborationPreference",
    "ConfidenceStyle",
    "ConvergenceDetector",
    "ConvergenceSignal",
    "DecisionStyle",
    "DynamicGuardrails",
    "ExpertDiversifier",
    "GuardrailConfig",
    "InfoCostBenefit",
    "MetaOrchestrator",
    "MetaRoutingDecision",
    "RecoveryStyle",
    "RoutingMode",
    "SandboxLevel",
    "SilverHabit",
    # Phase 2 — SOUL
    "SoulProfile",
    "TiltDetector",
    "UncertaintyAssessment",
    # Phase 1
    "UncertaintyAssessor",
    "get_archetype",
    "get_dynamic_guardrails",
    "list_archetypes",
    "register_archetype",
    "reset_dynamic_guardrails",
]
