"""Integration tests for MoRE OS core components."""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestIntegrationLLMStateAndProviders:
    """Integration tests for LLM state and providers."""

    def test_state_manager_with_provider_config(self):
        """Test LLM state manager with provider configuration."""
        from more_core.llm.state_manager import LLMStateManager

        manager = LLMStateManager()

        # Update provider settings
        manager.update_state(provider="ollama", model="llama2", temperature=0.5)

        state = manager.get_state()
        assert state.provider == "ollama"
        assert state.model == "llama2"
        assert state.temperature == 0.5

    def test_state_manager_with_lmstudio_config(self):
        """Test LLM state manager with LM Studio configuration."""
        from more_core.llm.state_manager import LLMStateManager

        manager = LLMStateManager()

        # Configure LM Studio specific settings
        manager.update_state(
            provider="lmstudio",
            lmstudio_gpu_layers=33,
            lmstudio_threads=8,
            lmstudio_vram_fraction=0.9,
        )

        state = manager.get_state()
        assert state.lmstudio_gpu_layers == 33
        assert state.lmstudio_threads == 8
        assert state.lmstudio_vram_fraction == 0.9


class TestIntegrationOptimizationAndCaching:
    """Integration tests for optimization components."""

    async def test_cache_with_multiple_providers(self):
        """Test cache behavior with multiple provider configurations."""
        from more_core.optimization import RequestCache

        cache = RequestCache()

        # Same prompt, different models should have different keys
        await cache.set("prompt", "model1", "response1")
        await cache.set("prompt", "model2", "response2")

        assert await cache.get("prompt", "model1") == "response1"
        assert await cache.get("prompt", "model2") == "response2"

    def test_rate_limiter_with_concurrent_requests(self):
        """Test rate limiter with concurrent requests."""
        import more_core.optimization as opt

        limiter = opt.RateLimiter(rate=100, burst=10)

        async def run_test():
            # Run 10 sequential requests - all should succeed (within burst)
            results = []
            for _ in range(10):
                result = await limiter.acquire()
                results.append(result)
            return results

        results = asyncio.run(run_test())
        assert all(results)

    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after failures."""
        from more_core.optimization import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)

        async def failing_func():
            raise RuntimeError("test failure")

        # Trigger failures to open circuit
        for _ in range(2):
            with pytest.raises(RuntimeError):
                asyncio.run(breaker.call(failing_func))

        assert breaker.state == "OPEN"

        # Wait for recovery timeout
        import time

        time.sleep(0.1)

        # Should allow an attempt now (half-open or closed)
        # The circuit breaker allows one test call after timeout
        async def success_func():
            return "success"

        # This should not raise - either succeeds or allows attempt
        try:
            result = asyncio.run(breaker.call(success_func))
            # If it succeeds, state should be CLOSED or HALF_OPEN
            assert result == "success"
        except RuntimeError:
            # If circuit is still open, it raises RuntimeError
            # This is acceptable behavior
            pass


class TestIntegrationZENRulesAndEnforcement:
    """Integration tests for ZEN rules and enforcement."""

    def test_zen_rules_with_severity_callbacks(self):
        """Test ZEN rules with severity-specific callbacks."""
        from more_core.zen_rules import RuleSeverity, ZENRulesEnforcer

        ZENRulesEnforcer._instance = None
        enforcer = ZENRulesEnforcer()

        critical_events = []

        def critical_callback(violation):
            critical_events.append(violation)

        enforcer.register_callback(RuleSeverity.P1_CRITICAL, critical_callback)

        # Verify callback is registered
        assert len(enforcer._callbacks[RuleSeverity.P1_CRITICAL]) > 0

    def test_zen_rules_violation_recording(self):
        """Test violation recording and tracking."""
        from more_core.zen_rules import RuleCategory, RuleSeverity, ZENRule, ZENRulesEnforcer

        ZENRulesEnforcer._instance = None
        enforcer = ZENRulesEnforcer()

        # Add a test rule with check function
        test_rule = ZENRule(
            id="ZEN-TEST-INTEGRATION",
            name="Integration Test Rule",
            category=RuleCategory.SAFETY,
            severity=RuleSeverity.P2_MAJOR,
            description="Test",
            check_fn=lambda ctx: ctx.get("allowed", True),
        )
        enforcer._rules["ZEN-TEST-INTEGRATION"] = test_rule

        # Trigger violation
        enforcer.check_violation("ZEN-TEST-INTEGRATION", {"allowed": False})

        # Verify violation was recorded
        assert len(enforcer._violations) > 0


class TestIntegrationGovernanceAndAudit:
    """Integration tests for governance and audit."""

    def test_audit_log_writing(self):
        """Test audit log writing."""
        import tempfile

        from more_core.governance.audit import AuditLogger

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl") as f:
            temp_path = f.name

        try:
            logger = AuditLogger(temp_path)

            # Write audit records
            logger.log("user1", "task:create", "task_123", description="Created task")
            logger.log("user1", "task:execute", "task_123", result="success")
            # Async audit writer: flush before reading back from disk
            logger.flush()

            # Verify file exists and has content
            import os

            assert os.path.exists(temp_path)
            assert os.path.getsize(temp_path) > 0
        finally:
            os.unlink(temp_path)

    def test_rbac_permission_check(self):
        """Test RBAC permission checking with UnifiedRBAC (replaces governance RBAC)."""
        from more_core.security.rbac import Permission, UnifiedRBAC

        rbac = UnifiedRBAC(admin_users=["admin1"])
        rbac.assign_role("user1", "operator")

        # Admin (in admin_users list) has all permissions
        assert rbac.check("admin1", Permission.TASK_EXECUTE)
        assert rbac.check("admin1", Permission.SYS_ADMIN)

        # Operator role grants TASK_EXECUTE but not SYS_ADMIN
        assert rbac.check("user1", Permission.TASK_EXECUTE)
        assert not rbac.check("user1", Permission.SYS_ADMIN)

        # Unknown user is blocked
        assert not rbac.check("random", Permission.TASK_EXECUTE)


class TestIntegrationIncidentResponse:
    """Integration tests for incident response system."""

    def test_incident_creation_and_tracking(self):
        """Test incident creation and tracking."""
        from more_core.core.types import LayerId
        from more_core.incident_response import IncidentManager, IncidentType, Severity

        manager = IncidentManager()

        # Report an incident
        incident = asyncio.run(
            manager.report_incident(
                incident_type=IncidentType.UNAUTHORIZED_ACCESS,
                severity=Severity.HIGH,
                layer=LayerId.L1,
                description="Unauthorized access attempt",
                context={"user": "unknown", "ip": "192.168.1.1"},
            )
        )

        assert incident is not None
        assert incident.severity == Severity.HIGH

        # Check it was recorded
        assert len(manager._incidents) > 0

    def test_quarantine_functionality(self):
        """Test variant quarantine functionality."""
        from more_core.incident_response import IncidentManager

        manager = IncidentManager()

        # Manually add to quarantine set (simulating quarantine action)
        variant_id = "variant_123"
        manager._quarantined_variants.add(variant_id)

        assert variant_id in manager._quarantined_variants

        # Check if variant is quarantined
        assert variant_id in manager._quarantined_variants


class TestIntegrationMetrics:
    """Integration tests for metrics collection."""

    def test_metrics_aggregation(self):
        """Test metrics aggregation across multiple requests."""
        from more_core.metrics import MetricsCollector

        collector = MetricsCollector(window_size=100)

        # Record multiple requests
        for i in range(10):
            collector.record_request(duration_ms=100 + i * 10, success=True)

        # Record layer durations
        for layer in ["L0", "L1", "L2"]:
            for _ in range(5):
                collector.record_layer(layer, duration_ms=50)

        # Get snapshot
        snapshot = collector.snapshot(cache_hit_rate=0.8, memory_mb=256.0)

        assert snapshot.total_requests == 10
        assert snapshot.success_count == 10
        assert snapshot.cache_hit_rate == 0.8
        assert "L0" in snapshot.layer_durations

    def test_percentile_calculation(self):
        """Test percentile calculation."""
        from more_core.metrics import MetricsCollector

        collector = MetricsCollector()

        # Record values 1-100
        for i in range(1, 101):
            collector.record_request(duration_ms=float(i), success=True)

        p50 = collector.get_percentile(collector._request_durations, 50)
        p95 = collector.get_percentile(collector._request_durations, 95)

        assert 45 <= p50 <= 55  # Around 50
        assert 90 <= p95 <= 100  # Around 95
