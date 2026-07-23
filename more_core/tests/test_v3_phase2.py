

# ── Phase 2: SOUL Profile tests ─────────────────────────────────────────

class TestSoulProfile:
    def test_create_default_profile(self):
        from more_core.v3.soul_profile import SoulProfile
        profile = SoulProfile()
        assert profile.risk_appetite == 0.5
        assert profile.decision_style.value == "evidence_based"
        assert len(profile.habits) >= 3

    def test_personality_vector(self):
        from more_core.v3.soul_profile import SoulProfile
        profile = SoulProfile(risk_appetite=0.8, creativity=0.9)
        vec = profile.personality_vector()
        assert len(vec) == 7
        assert vec[0] == 0.8  # risk_appetite
        assert vec[1] == 0.9  # creativity

    def test_personality_match_similar(self):
        from more_core.v3.soul_profile import SoulProfile
        a = SoulProfile(risk_appetite=0.7, creativity=0.8)
        b = SoulProfile(risk_appetite=0.7, creativity=0.8)
        score = a.personality_match_score(b)
        assert score > 0.95  # nearly identical

    def test_personality_match_different(self):
        from more_core.v3.soul_profile import SoulProfile
        # Alternating high/low patterns — not proportional
        a = SoulProfile(risk_appetite=0.9, creativity=0.1, decision_speed=0.9,
                        resilience=0.1, adaptability=0.9, cooperativeness=0.1,
                        assertiveness=0.9)
        b = SoulProfile(risk_appetite=0.1, creativity=0.9, decision_speed=0.1,
                        resilience=0.9, adaptability=0.1, cooperativeness=0.9,
                        assertiveness=0.1)
        score = a.personality_match_score(b)
        # Alternating vectors have low cosine similarity
        assert score < 0.5

    def test_habit_strength_active(self):
        from more_core.v3.soul_profile import SoulProfile, SilverHabit
        profile = SoulProfile(habits=[SilverHabit.STOP_LOSS_DISCIPLINE])
        assert profile.habit_strength(SilverHabit.STOP_LOSS_DISCIPLINE) > 0.5
        assert profile.habit_strength(SilverHabit.DIVERSIFIED_BETTING) < 0.3

    def test_serialize_roundtrip(self):
        from more_core.v3.soul_profile import SoulProfile, DecisionStyle
        original = SoulProfile(
            name="test", risk_appetite=0.6,
            decision_style=DecisionStyle.INTUITIVE,
        )
        data = original.to_dict()
        restored = SoulProfile.from_dict(data)
        assert restored.name == "test"
        assert restored.risk_appetite == 0.6
        assert restored.decision_style == DecisionStyle.INTUITIVE

    def test_archetype_risk_analyst(self):
        from more_core.v3.soul_profile import ARCHETYPE_RISK_ANALYST, SilverHabit
        assert ARCHETYPE_RISK_ANALYST.risk_appetite < 0.4
        assert ARCHETYPE_RISK_ANALYST.confidence_style.value == "calibrated"
        assert SilverHabit.PROBABILISTIC_THINKING in ARCHETYPE_RISK_ANALYST.habits

    def test_archetype_innovator(self):
        from more_core.v3.soul_profile import ARCHETYPE_INNOVATOR
        assert ARCHETYPE_INNOVATOR.risk_appetite > 0.7
        assert ARCHETYPE_INNOVATOR.creativity > 0.8
        assert ARCHETYPE_INNOVATOR.decision_style.value == "intuitive"

    def test_archetype_registry(self):
        from more_core.v3.soul_profile import get_archetype, list_archetypes
        names = list_archetypes()
        assert "risk_analyst" in names
        assert "innovator" in names
        assert get_archetype("risk_analyst") is not None
        assert get_archetype("nonexistent") is None


# ── Phase 2: Silver Habits tests ────────────────────────────────────────

class TestCircuitBreaker:
    def test_triple_breaker_normal(self):
        from more_core.v3.silver_habits import CircuitBreakerState
        cb = CircuitBreakerState(token_limit=100, time_limit_s=10, cost_limit_usd=0.01)
        assert not cb.is_breached
        assert cb.consume(50, 0.001)
        assert cb.tokens_used == 50

    def test_triple_breaker_token_limit(self):
        from more_core.v3.silver_habits import CircuitBreakerState
        cb = CircuitBreakerState(token_limit=10, time_limit_s=100, cost_limit_usd=100)
        assert cb.consume(9)
        assert not cb.consume(2)  # Would exceed, state unchanged
        assert cb.tokens_used == 9  # Failed consume doesn't add
        # Now consume exactly to hit the limit
        assert cb.consume(1)        # 9+1 = 10 = limit
        assert cb.is_breached
        assert "token" in cb.breach_reason.lower()

    def test_triple_breaker_cost_limit(self):
        from more_core.v3.silver_habits import CircuitBreakerState
        cb = CircuitBreakerState(token_limit=1000, time_limit_s=100, cost_limit_usd=0.001)
        assert not cb.consume(10, 0.002)  # Cost exceeds


class TestTiltDetector:
    def test_no_tilt_initially(self):
        from more_core.v3.silver_habits import TiltDetector
        td = TiltDetector(window_size=3)
        assert not td.is_tilting
        assert td.streak_length == 0

    def test_tilt_after_consecutive_failures(self):
        from more_core.v3.silver_habits import TiltDetector
        td = TiltDetector(window_size=3, tilt_threshold=0.6)
        td.record_outcome(False)
        td.record_outcome(False)
        td.record_outcome(False)
        assert td.is_tilting
        assert td.streak_length == 3

    def test_tilt_resets_after_success(self):
        from more_core.v3.silver_habits import TiltDetector
        td = TiltDetector(window_size=5, tilt_threshold=0.6)
        td.record_outcome(False)
        td.record_outcome(False)
        td.record_outcome(True)
        td.record_outcome(True)
        td.record_outcome(True)
        # Only 2 failures in 5 = 0.4 < 0.6 → not tilting
        assert not td.is_tilting
        assert td.streak_length == 0


class TestConvergenceDetector:
    def test_no_convergence_initially(self):
        from more_core.v3.silver_habits import ConvergenceDetector
        cd = ConvergenceDetector(stagnation_threshold=3)
        signal = cd.record_quality(0.5)
        assert not signal.should_terminate

    def test_convergence_after_stagnation(self):
        from more_core.v3.silver_habits import ConvergenceDetector
        cd = ConvergenceDetector(stagnation_threshold=2, min_improvement=0.1)
        cd.record_quality(0.5)
        cd.record_quality(0.51)  # < 0.1 improvement → stagnation
        cd.record_quality(0.51)  # Same → stagnation count = 2
        signal = cd.record_quality(0.515)  # stagnation count = 3 → terminate
        assert signal.should_terminate

    def test_max_iterations(self):
        from more_core.v3.silver_habits import ConvergenceDetector
        cd = ConvergenceDetector(max_iterations=3)
        cd.record_quality(0.5)
        cd.record_quality(0.6)
        signal = cd.record_quality(0.7)  # iteration 3 = max
        assert signal.should_terminate


class TestChaosInjector:
    def test_epsilon_bounded(self):
        from more_core.v3.silver_habits import ChaosInjector
        ci = ChaosInjector(epsilon=0.1)
        for _ in range(100):
            assert 0.001 <= ci.current_epsilon <= 0.1
            ci.should_explore()

    def test_epsilon_decays(self):
        from more_core.v3.silver_habits import ChaosInjector
        ci = ChaosInjector(epsilon=0.1, decay=0.9)
        for _ in range(20):
            ci.should_explore()
        assert ci.current_epsilon < 0.05


class TestInfoCostBenefit:
    def test_positive_ev(self):
        from more_core.v3.silver_habits import InfoCostBenefit
        icb = InfoCostBenefit(cost_per_token=0.000001)
        should, reason = icb.should_acquire(
            estimated_tokens=100, decision_impact=0.5, current_uncertainty=0.8,
        )
        assert should
        assert "+EV" in reason

    def test_negative_ev(self):
        from more_core.v3.silver_habits import InfoCostBenefit
        icb = InfoCostBenefit(cost_per_token=0.001)
        should, reason = icb.should_acquire(
            estimated_tokens=10000, decision_impact=0.1, current_uncertainty=0.1,
        )
        assert not should
        assert "-EV" in reason


class TestExpertDiversifier:
    def test_underused_gets_bonus(self):
        from more_core.v3.silver_habits import ExpertDiversifier
        ed = ExpertDiversifier(diversity_weight=0.2)
        ed.record_usage("expert_a")
        ed.record_usage("expert_a")
        ed.record_usage("expert_b")
        # expert_b used less → higher diversity bonus
        assert ed.diversity_bonus("expert_b") > ed.diversity_bonus("expert_a")


class TestCollaborationBonus:
    def test_synergy_learning(self):
        from more_core.v3.silver_habits import CollaborationBonus
        cb = CollaborationBonus(learning_rate=0.5)
        assert cb.synergy_bonus("A", "B") == 0.0  # No history
        cb.record_collaboration("A", "B", 0.9)  # Great outcome
        assert cb.synergy_bonus("A", "B") > 0.2  # Learned synergy


# ── Phase 2: Meta-Orchestrator personality routing ──────────────────────

class TestPersonalityRouting:
    def test_select_expert_with_personality(self):
        from more_core.v3.meta_orchestrator import MetaOrchestrator
        from more_core.v3.soul_profile import ARCHETYPE_RISK_ANALYST, ARCHETYPE_INNOVATOR
        from more_core.core.types import TaskType

        meta = MetaOrchestrator()
        candidates = [
            {"id": "a", "capability": 0.8, "soul_profile": ARCHETYPE_RISK_ANALYST},
            {"id": "b", "capability": 0.8, "soul_profile": ARCHETYPE_INNOVATOR},
        ]
        # Architecture design with high uncertainty → prefer risk analyst
        best = meta.select_expert(TaskType.ARCHITECTURE_DESIGN, candidates)
        assert best is not None
        assert "id" in best

    def test_select_expert_no_soul_fallback(self):
        from more_core.v3.meta_orchestrator import MetaOrchestrator
        from more_core.core.types import TaskType

        meta = MetaOrchestrator()
        candidates = [
            {"id": "a", "capability": 0.9},
            {"id": "b", "capability": 0.5},
        ]
        best = meta.select_expert(TaskType.NLP_TASK, candidates)
        # Higher capability should win when no personality data
        assert best["id"] == "a"

    def test_select_expert_empty(self):
        from more_core.v3.meta_orchestrator import MetaOrchestrator
        from more_core.core.types import TaskType
        meta = MetaOrchestrator()
        assert meta.select_expert(TaskType.NLP_TASK, []) is None
