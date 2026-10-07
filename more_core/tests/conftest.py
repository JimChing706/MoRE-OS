"""Pytest configuration and fixtures for MoRE OS tests."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 开发者本地 more_core/.env 里的 LLM 性能/路由调优不得泄漏进测试环境：
# ``core.config._load_dotenv()`` 在 import 时把 .env 写进 os.environ，若不清掉，
# 本地把 MORE_TIER_*/MORE_LLM_*/MORE_COUNCIL_* 调过之后会翻转无关的路由断言
# （如"T0 是 reasoning-distilled"）。测试需要这些旋钮时显式 monkeypatch.setenv。
# 注意：必须"设为空串"而不是 del —— ``core.config._load_dotenv()`` 用的是
# ``load_dotenv(override=False)``，只有当 key **不存在**时才会被 .env 覆盖。
# 占位为空串可同时满足：① 阻止 .env 灌入；② 各读取点把空串当作"未配置"→ 用默认。
for _ambient_llm_var in (
    "MORE_LLM_FALLBACK_DEADLINE_S",
    "MORE_LLM_MAX_TOKENS",
    "MORE_OLLAMA_TIMEOUT",
    "MORE_LMSTUDIO_TIMEOUT",
    "MORE_COUNCIL_MAX_ROLES",
    "MORE_COUNCIL_CROSS_REVIEW",
    "MORE_TIER_0_MODEL",
    "MORE_TIER_1_MODEL",
    "MORE_TIER_2_MODEL",
    "MORE_TIER_3_MODEL",
    "MORE_PREV_TIER_0_MODEL",
    "MORE_PREV_TIER_1_MODEL",
    "MORE_PREV_TIER_2_MODEL",
    "MORE_PREV_TIER_3_MODEL",
    "MORE_DISABLE_TIER_0",
):
    os.environ[_ambient_llm_var] = ""

# 测试默认跳过技能出网自检（避免每个 TestClient 用例都做真实 DNS/TCP 探测）。
# 需要该行为的用例直接调用 check_skill_network() 或 monkeypatch 探测函数。
os.environ.setdefault("MORE_SKIP_SKILL_NETWORK_PREFLIGHT", "1")


@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing."""
    return {
        "choices": [{"message": {"content": "Test response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


@pytest.fixture
def sample_context():
    """Sample context for testing."""
    return {
        "user_id": "test_user",
        "session_id": "test_session",
        "message": "test message",
        "timestamp": "2026-05-06T00:00:00",
    }


@pytest.fixture
def mock_provider():
    """Mock LLM provider for testing."""

    class MockProvider:
        def __init__(self):
            self.name = "mock"
            self.config = {"api_key": "test_key", "base_url": "http://localhost"}

        async def generate(self, prompt, **kwargs):
            return {"choices": [{"message": {"content": "mock response"}}]}

        def supports_vision(self):
            return False

        def supports_function_calling(self):
            return False

    return MockProvider()


@pytest.fixture
def temp_dir(tmp_path):
    """Temporary directory for file operations."""
    return tmp_path


class _FakeLLMProvider:
    """In-memory LLM provider returning a fixed response for tests.

    Supports optional error injection and latency simulation.
    """

    name = "fake"

    def __init__(self, inject_errors: bool = False, latency_ms: float = 0):
        self._inject_errors = inject_errors
        self._latency_ms = latency_ms

    async def generate(self, request):
        if self._inject_errors:
            raise ConnectionError("Simulated LLM failure")
        if self._latency_ms > 0:
            import asyncio

            await asyncio.sleep(self._latency_ms / 1000)
        from more_core.llm.provider import LLMResponse

        return LLMResponse(
            content="fake-reply",
            provider="fake",
            model="fake-model",
            prompt_tokens=5,
            completion_tokens=256,
        )

    async def stream(self, request):
        if self._inject_errors:
            raise ConnectionError("Simulated stream failure")
        if self._latency_ms > 0:
            import asyncio

            await asyncio.sleep(self._latency_ms / 1000)
        yield "fake-reply"

    async def health(self):
        return not self._inject_errors


@pytest.fixture
def core():
    """Create a minimal MoRECore instance for testing."""
    from more_core.core.config import Settings
    from more_core.runtime.orchestrator import MoRECore

    settings = Settings(
        plugin_dir="tests/plugins",
        log_dir="tests/logs",
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
        # Step-3 P1 default gates are ON in production; turn OFF for fast
        # deterministic unit tests that exercise only the path under test.
        codegen_candidates=1,
        codegen_review=False,
    )
    instance = MoRECore(settings)
    # Inject fake LLM so tests that call core.execute() work without real providers
    instance.llm._providers["fake"] = _FakeLLMProvider()
    instance.llm._fallback = ["fake"]
    # 对齐生产 bootstrap：注册内置工具（含 python_exec）。否则代码类任务
    # 永远不会进沙箱，Codegen Controller 会因 sandbox=False 判 escalated，
    # 在 G1 交叉校验下被正确拦截 —— 那是测试夹具缺陷，不是产品缺陷。
    from more_core.tools.builtins import register_builtins

    register_builtins(instance.tools, instance)
    return instance


@pytest.fixture(autouse=True)
def _isolated_api_key_store(tmp_path, monkeypatch):
    """Keep every test off the developer's real ``data/api_keys.db``.

    The managed key registry decides whether the API requires authentication at
    all, so a populated production store would silently flip unrelated tests
    from "open dev mode" to 401.  Point the singleton at a per-test temp DB.
    """
    from more_core.security.api_key_store import set_default_store

    monkeypatch.setenv("MORE_API_KEY_DB", str(tmp_path / "api_keys.db"))
    monkeypatch.setenv("MORE_API_KEY_PEPPER", "more-os-test-pepper")
    set_default_store(None)
    yield
    set_default_store(None)


@pytest.fixture(autouse=True)
def _no_ambient_api_key(monkeypatch):
    """Never let the developer's ``more_core/.env`` decide test auth behaviour.

    ``core.config`` loads that file at import time, so a machine with a real
    ``MORE_API_KEY`` turned every unauthenticated TestClient call into a 401.
    Tests that need a key set it explicitly via ``monkeypatch.setenv``.
    """
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    # 生产 .env 可能开启 MORE_REQUIRE_API_KEY=1（严格模式）；测试需保持
    # 可复现的"无密钥开发模式"，否则 create_app() 会在启动校验处直接抛错。
    monkeypatch.setenv("MORE_REQUIRE_API_KEY", "0")
    yield


@pytest.fixture(autouse=True)
def _isolated_delivery_ledger(tmp_path, monkeypatch):
    """Keep delivery-ledger writes out of the developer's real data/ ledger."""
    from more_core.codegen.delivery_ledger import set_default_ledger

    monkeypatch.setenv("MORE_DELIVERY_LEDGER_DB", str(tmp_path / "delivery_ledger.db"))
    set_default_ledger(None)
    yield
    set_default_ledger(None)


@pytest.fixture(autouse=True)
def _isolated_skill_ledger(tmp_path, monkeypatch):
    """技能交付台账不得写入开发者真实 data/ 目录。"""
    from more_core.skills.delivery import set_default_skill_ledger

    monkeypatch.setenv("MORE_SKILL_LEDGER_DB", str(tmp_path / "skill_deliverables.db"))
    set_default_skill_ledger(None)
    yield
    set_default_skill_ledger(None)


@pytest.fixture(autouse=True)
def _isolated_observability(tmp_path, monkeypatch):
    """Telemetry must never leak between tests (or into the real logs/ DB)."""
    from more_core.governance import observability as _obs

    _obs.configure(tmp_path / "observability.sqlite")
    yield
    _obs.close()
