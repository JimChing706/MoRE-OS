"""MoRE v3.0 — Risk-Decision Operating System enhancements.

Phase 1: Meta-Orchestrator + Dynamic Guardrails
Phase 2: SOUL Personality Profiles + Silver Habits Engineering
"""

from .uncertainty import UncertaintyAssessor, UncertaintyAssessment
from .meta_orchestrator import MetaOrchestrator, MetaRoutingDecision, RoutingMode
from .dynamic_guardrails import (
    DynamicGuardrails,
    GuardrailConfig,
    SandboxLevel,
    get_dynamic_guardrails,
    reset_dynamic_guardrails,
)
from .soul_profile import (
    SoulProfile,
    SilverHabit,
    DecisionStyle,
    ConfidenceStyle,
    RecoveryStyle,
    CollaborationPreference,
    get_archetype,
    list_archetypes,
    register_archetype,
    ARCHETYPE_RISK_ANALYST,
    ARCHETYPE_INNOVATOR,
    ARCHETYPE_DIPLOMAT,
    ARCHETYPE_ENGINEER,
)
from .silver_habits import (
    CalibratedOutput,
    CircuitBreakerState,
    TiltDetector,
    ChaosInjector,
    ConvergenceDetector,
    ConvergenceSignal,
    InfoCostBenefit,
    ExpertDiversifier,
    CollaborationBonus,
)

__all__ = [
    # Phase 1
    "UncertaintyAssessor",
    "UncertaintyAssessment",
    "MetaOrchestrator",
    "MetaRoutingDecision",
    "RoutingMode",
    "DynamicGuardrails",
    "GuardrailConfig",
    "SandboxLevel",
    "get_dynamic_guardrails",
    "reset_dynamic_guardrails",
    # Phase 2 — SOUL
    "SoulProfile",
    "SilverHabit",
    "DecisionStyle",
    "ConfidenceStyle",
    "RecoveryStyle",
    "CollaborationPreference",
    "get_archetype",
    "list_archetypes",
    "register_archetype",
    "ARCHETYPE_RISK_ANALYST",
    "ARCHETYPE_INNOVATOR",
    "ARCHETYPE_DIPLOMAT",
    "ARCHETYPE_ENGINEER",
    # Phase 2 — Silver Habits
    "CalibratedOutput",
    "CircuitBreakerState",
    "TiltDetector",
    "ChaosInjector",
    "ConvergenceDetector",
    "ConvergenceSignal",
    "InfoCostBenefit",
    "ExpertDiversifier",
    "CollaborationBonus",
]
