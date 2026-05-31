"""Additional integration tests - Import verification."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestModuleImports:
    """Test that all modules can be imported - critical for system integrity."""

    def test_core_event_bus_import(self):
        """Test EventBus can be imported."""
        from more_core.core.event_bus import EventBus, Event
        assert EventBus is not None
        assert Event is not None

    def test_core_service_registry_import(self):
        """Test ServiceRegistry can be imported."""
        from more_core.core.service_registry import ServiceRegistry
        assert ServiceRegistry is not None

    def test_core_config_import(self):
        """Test config can be imported."""
        from more_core.core.config import Settings, LLMProviderConfig
        from more_core.core.config import LLMProviderName
        assert Settings is not None
        assert LLMProviderConfig is not None

    def test_core_types_import(self):
        """Test types can be imported."""
        from more_core.core.types import TaskRequest, TaskType, TaskStatus
        from more_core.core.types import LayerId, ReasoningStep
        assert TaskRequest is not None
        assert TaskType.NLP_TASK is not None

    def test_core_errors_import(self):
        """Test errors can be imported."""
        from more_core.core.errors import MoREError, LLMError
        from more_core.core.errors import SandboxError, GovernanceError
        assert MoREError is not None
        assert LLMError is not None

    def test_llm_manager_import(self):
        """Test LLM manager can be imported."""
        from more_core.llm.manager import LLMManager
        assert LLMManager is not None

    def test_llm_state_manager_import(self):
        """Test LLM state manager can be imported."""
        from more_core.llm.state_manager import LLMStateManager, LLMCallState
        assert LLMStateManager is not None
        assert LLMCallState is not None

    def test_llm_providers_import(self):
        """Test LLM providers can be imported."""
        from more_core.llm.providers.ollama import OllamaProvider
        from more_core.llm.providers.lmstudio import LMStudioProvider
        from more_core.llm.providers.deepseek import DeepSeekProvider
        from more_core.llm.providers.openai_compat import OpenAICompatProvider
        assert OllamaProvider is not None
        assert LMStudioProvider is not None

    def test_layers_import(self):
        """Test layers can be imported."""
        from more_core.layers import l0_execution
        from more_core.layers import l1_orchestration
        from more_core.layers import l2_evolution
        from more_core.layers import l3_symbolic
        from more_core.layers import l4_cognition
        assert l0_execution is not None

    def test_tools_registry_import(self):
        """Test tools registry can be imported."""
        from more_core.tools.registry import ToolRegistry, ToolDefinition, ToolResult
        assert ToolRegistry is not None

    def test_tools_builtins_import(self):
        """Test tools builtins can be imported."""
        from more_core.tools import builtins
        assert builtins is not None

    def test_governance_rbac_import(self):
        """Test RBAC can be imported."""
        from more_core.governance.rbac import RBACPolicy, Role, Permission
        from more_core.governance.rbac import ROLE_PERMISSIONS
        assert RBACPolicy is not None
        assert Role.ADMIN is not None

    def test_governance_audit_import(self):
        """Test audit can be imported."""
        from more_core.governance.audit import AuditLogger, AuditRecord
        assert AuditLogger is not None

    def test_governance_policy_import(self):
        """Test policy can be imported."""
        from more_core.governance.policy import PolicyEnforcer
        assert PolicyEnforcer is not None

    def test_zen_rules_import(self):
        """Test ZEN rules can be imported."""
        from more_core.zen_rules import ZENRulesEnforcer, ZENRule
        from more_core.zen_rules import RuleSeverity, RuleCategory
        from more_core.zen_rules import ViolationRecord
        assert ZENRulesEnforcer is not None
        assert RuleSeverity.P0_FATAL is not None

    def test_optimization_import(self):
        """Test optimization can be imported."""
        from more_core.optimization import RequestCache, CacheConfig
        from more_core.optimization import CacheStrategy
        from more_core.optimization import RateLimiter, CircuitBreaker
        from more_core.optimization import with_retry, with_timeout
        assert RequestCache is not None
        assert RateLimiter is not None

    def test_metrics_import(self):
        """Test metrics can be imported."""
        from more_core.metrics import MetricsCollector, MetricPoint
        from more_core.metrics import PerformanceSnapshot
        assert MetricsCollector is not None

    def test_incident_response_import(self):
        """Test incident response can be imported."""
        from more_core.incident_response import IncidentManager, Incident
        from more_core.incident_response import Severity, IncidentType
        assert IncidentManager is not None
        assert Severity.HIGH is not None

    def test_memory_store_import(self):
        """Test memory store can be imported."""
        from more_core.memory.store import MemoryStore
        assert MemoryStore is not None

    def test_evolution_archive_import(self):
        """Test evolution archive can be imported."""
        from more_core.evolution.archive import EvolutionArchive
        assert EvolutionArchive is not None

    def test_router_layer_router_import(self):
        """Test layer router can be imported."""
        from more_core.router.layer_router import LayerRouter, RoutingDecision
        assert LayerRouter is not None

    def test_sandbox_import(self):
        """Test sandbox can be imported."""
        from more_core.sandbox.secure_sandbox import SecureSandbox
        from more_core.sandbox.subprocess_sandbox import SubprocessSandbox
        assert SecureSandbox is not None

    def test_plugins_manager_import(self):
        """Test plugins manager can be imported."""
        from more_core.plugins.manager import PluginManager
        from more_core.plugins import interface
        assert PluginManager is not None

    def test_channels_manager_import(self):
        """Test channels manager can be imported."""
        from more_core.channels.manager import ChannelManager
        from more_core.channels.formatter import MessageFormatter
        assert ChannelManager is not None

    def test_mcp_registry_import(self):
        """Test MCP registry can be imported."""
        from more_core.mcp.registry import MCPRegistry, ToolRegistry as MCPToolRegistry
        assert MCPRegistry is not None

    def test_cron_scheduler_import(self):
        """Test cron scheduler can be imported."""
        from more_core.cron.scheduler import CronScheduler
        from more_core.cron.trigger import Trigger
        assert CronScheduler is not None

    def test_a2a_client_import(self):
        """Test A2A client can be imported."""
        from more_core.a2a.client import A2AClient
        assert A2AClient is not None

    def test_ontology_engine_import(self):
        """Test ontology engine can be imported."""
        from more_core.ontology.engine import OntologyEngine
        from more_core.ontology.rule_engine import RuleEngine
        assert OntologyEngine is not None

    def test_runtime_orchestrator_import(self):
        """Test orchestrator can be imported."""
        from more_core.runtime.orchestrator import MoRECore
        assert MoRECore is not None

    def test_api_server_import(self):
        """Test API server can be imported."""
        from more_core.api.server import create_app
        assert create_app is not None


class TestBasicFunctionality:
    """Test basic functionality without external dependencies."""

    def test_settings_default_values(self):
        """Test Settings has correct defaults."""
        from more_core.core.config import Settings
        s = Settings()
        assert s.enable_symbolic is True
        assert s.enable_evolution is False
        assert s.enable_metacognition is False

    def test_task_type_values(self):
        """Test TaskType enum values."""
        from more_core.core.types import TaskType
        assert TaskType.NLP_TASK.value == "nlp_task"
        assert TaskType.CODE_GENERATION.value == "code_generation"

    def test_layer_id_values(self):
        """Test LayerId enum values."""
        from more_core.core.types import LayerId
        assert LayerId.L0.value == "L0"
        assert LayerId.L5.value == "L5"

    def test_role_values(self):
        """Test Role enum values."""
        from more_core.governance.rbac import Role
        assert Role.ADMIN.value == "admin"
        assert Role.USER.value == "user"

    def test_rbac_policy_creation(self):
        """Test RBAC policy can be created."""
        from more_core.governance.rbac import RBACPolicy, User, Role
        policy = RBACPolicy()
        user = User(id="test", name="Test", role=Role.ADMIN)
        policy.add_user(user)
        assert policy.get_user("test") is not None

    def test_zen_rules_default_rules(self):
        """Test ZEN rules enforcer has default rules."""
        from more_core.zen_rules import ZENRulesEnforcer
        enforcer = ZENRulesEnforcer()
        assert len(enforcer._rules) >= 15

    def test_cache_basic_operations(self):
        """Test cache basic operations."""
        from more_core.optimization import RequestCache
        cache = RequestCache()
        cache.set("prompt", "model", "value")
        assert cache.get("prompt", "model") == "value"

    def test_cache_clear(self):
        """Test cache clear."""
        from more_core.optimization import RequestCache
        cache = RequestCache()
        cache.set("p", "m", "v")
        cache.clear()
        assert cache.get("p", "m") is None

    def test_rate_limiter_initialization(self):
        """Test rate limiter initialization."""
        from more_core.optimization import RateLimiter
        limiter = RateLimiter(rate=10, burst=20)
        assert limiter._rate == 10
        assert limiter._burst == 20

    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initialization."""
        from more_core.optimization import CircuitBreaker
        breaker = CircuitBreaker(failure_threshold=5)
        assert breaker.state == "CLOSED"

    def test_metrics_record_request(self):
        """Test metrics recording."""
        from more_core.metrics import MetricsCollector
        collector = MetricsCollector()
        collector.record_request(100.0, True)
        snapshot = collector.snapshot()
        assert snapshot.total_requests == 1
        assert snapshot.success_count == 1

    def test_llm_state_singleton(self):
        """Test LLM state manager is singleton."""
        from more_core.llm.state_manager import LLMStateManager
        LLMStateManager._instance = None
        m1 = LLMStateManager()
        m2 = LLMStateManager()
        assert m1 is m2

    def test_tool_registry_creation(self):
        """Test tool registry creation."""
        from more_core.tools.registry import ToolRegistry
        registry = ToolRegistry()
        assert hasattr(registry, '_tools')
        assert len(registry.list_tools()) == 0