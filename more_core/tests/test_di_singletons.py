"""TD-05: singletons must be instantiable and injectable for testing.

Covers:
- LLMStateManager: plain class (no __new__ singleton) — fresh instances are independent;
  get_llm_state_manager() still returns the shared app-wide instance.
- IncidentManager: independent instances; L2/L5 layers use the manager injected
  via ctx.core.incident_manager instead of the global singleton.
"""

from types import SimpleNamespace

import pytest

from more_core.core.types import LayerId
from more_core.incident_response import IncidentManager, get_incident_manager
from more_core.layers.l5_metacognition import MetacognitionLayer
from more_core.llm.state_manager import LLMStateManager, get_llm_state_manager


class TestLLMStateManagerInstantiable:
    def test_fresh_instances_are_independent(self):
        a = LLMStateManager()
        b = LLMStateManager()
        assert a is not b
        a.update_state(temperature=0.11)
        assert b.get_state().temperature != 0.11

    def test_global_getter_returns_shared_instance(self):
        assert get_llm_state_manager() is get_llm_state_manager()

    def test_fresh_instance_does_not_pollute_global(self):
        global_temp = get_llm_state_manager().get_state().temperature
        local = LLMStateManager()
        local.update_state(temperature=0.99)
        assert get_llm_state_manager().get_state().temperature == global_temp

    def test_usage_stats_are_per_instance(self):
        a = LLMStateManager()
        b = LLMStateManager()
        a.record_usage("lmstudio", tokens=10, cost=0.0, latency_ms=5.0)
        assert a.get_usage().total_requests == 1
        assert b.get_usage().total_requests == 0


class TestIncidentManagerInjectable:
    def test_instances_are_independent(self):
        a = IncidentManager()
        b = IncidentManager()
        a._blocked_actors.add("mallory")
        assert a.is_actor_blocked("mallory")
        assert not b.is_actor_blocked("mallory")

    @pytest.mark.asyncio
    async def test_l5_uses_injected_incident_manager(self):
        injected = IncidentManager()
        injected._blocked_actors.add("mallory")

        ctx = SimpleNamespace(
            core=SimpleNamespace(incident_manager=injected),
            request=SimpleNamespace(id="req-1", context={"actor": "mallory"}),
            scratch={},
        )

        result = await MetacognitionLayer().process(ctx)

        assert result.layer == LayerId.L5
        assert result.output.get("blocked") is True
        # The incident landed in the injected manager, not the global one
        assert len(injected.get_active_incidents()) == 1
        global_ids = {i.id for i in get_incident_manager().get_active_incidents()}
        assert {i.id for i in injected.get_active_incidents()}.isdisjoint(global_ids)
