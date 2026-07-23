"""Tests for LLM Manager."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from more_core.llm.state_manager import LLMStateManager, LLMCallState, LLMUsageStats
from more_core.llm.providers.ollama import OllamaProvider
from more_core.llm.providers.lmstudio import LMStudioProvider
from more_core.llm.providers.deepseek import DeepSeekProvider


class TestLLMStateManager:
    """Test suite for LLM State Manager."""

    def test_state_manager_initialization(self):
        """Test state manager initializes correctly."""
        # Use a fresh instance by resetting singleton
        LLMStateManager._instance = None
        manager = LLMStateManager()
        assert manager is not None

    def test_get_state(self):
        """Test getting LLM state."""
        LLMStateManager._instance = None
        manager = LLMStateManager()
        state = manager.get_state()
        assert state is not None
        assert isinstance(state, LLMCallState)
        assert state.provider == "lmstudio"

    def test_update_state(self):
        """Test updating LLM state."""
        LLMStateManager._instance = None
        manager = LLMStateManager()
        result = manager.update_state(temperature=0.8)
        assert isinstance(result, LLMCallState)
        assert result.temperature == 0.8

    def test_reset_state(self):
        """Test resetting LLM state."""
        LLMStateManager._instance = None
        manager = LLMStateManager()
        manager.update_state(temperature=0.9)
        manager.reset_state()
        state = manager.get_state()
        assert state.temperature == 0.7  # default

    def test_get_usage(self):
        """Test getting usage statistics."""
        LLMStateManager._instance = None
        manager = LLMStateManager()
        stats = manager.get_usage()
        assert stats is not None
        assert isinstance(stats, LLMUsageStats)


class TestOllamaProvider:
    """Test suite for Ollama provider."""

    def test_ollama_provider(self):
        """Test Ollama provider configuration."""
        provider = OllamaProvider(
            name="ollama",
            endpoint="http://localhost:11434",
            model="llama2"
        )
        assert provider.name == "ollama"
        # Check attributes exist
        assert hasattr(provider, 'model')


class TestLMStudioProvider:
    """Test suite for LM Studio provider."""

    def test_lmstudio_provider(self):
        """Test LM Studio provider configuration."""
        provider = LMStudioProvider(
            name="lmstudio",
            endpoint="http://localhost:1234",
            model="local-model"
        )
        assert provider.name == "lmstudio"


class TestDeepSeekProvider:
    """Test suite for DeepSeek provider."""

    def test_deepseek_provider(self):
        """Test DeepSeek provider configuration."""
        provider = DeepSeekProvider(
            name="deepseek",
            endpoint="https://api.deepseek.com",
            model="deepseek-chat",
            api_key="test_key"
        )
        assert provider.name == "deepseek"


class TestLLMCallState:
    """Test suite for LLMCallState."""

    def test_default_state(self):
        """Test default state values."""
        state = LLMCallState()
        assert state.provider == "lmstudio"
        assert state.temperature == 0.7
        assert state.max_tokens == 2048
        assert state.lmstudio_gpu_layers == -1

    def test_state_modification(self):
        """Test state can be modified."""
        state = LLMCallState()
        state.temperature = 0.9
        assert state.temperature == 0.9


class TestLLMUsageStats:
    """Test suite for LLMUsageStats."""

    def test_default_stats(self):
        """Test default stats values."""
        stats = LLMUsageStats()
        assert stats.total_requests == 0
        assert stats.total_tokens == 0
        assert stats.total_cost == 0.0
        assert isinstance(stats.provider_usage, dict)