"""Pytest configuration and fixtures for MoRE OS tests."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing."""
    return {
        "choices": [{"message": {"content": "Test response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20}
    }


@pytest.fixture
def sample_context():
    """Sample context for testing."""
    return {
        "user_id": "test_user",
        "session_id": "test_session",
        "message": "test message",
        "timestamp": "2026-05-06T00:00:00"
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
            completion_tokens=10,
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
    )
    instance = MoRECore(settings)
    # Inject fake LLM so tests that call core.execute() work without real providers
    instance.llm._providers["fake"] = _FakeLLMProvider()
    instance.llm._fallback = ["fake"]
    return instance