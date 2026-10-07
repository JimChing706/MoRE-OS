"""Tests for OpenFang v0.6.1–v0.6.9 parity features."""

import pytest
import time
from more_core.llm.reasoning import (
    is_reasoning_model,
    supports_budget_tokens,
    get_reasoning_params,
    ReasoningRouter,
)
from more_core.llm.model_aliases import ModelAliasRegistry, ModelAlias
from more_core.channels.reconnect import ReconnectManager, ReconnectConfig, ReconnectState
from more_core.channels.base import Message, Response, MediaType, MediaAttachment
from more_core.hands.persistence import HandPersistence
from more_core.hands.browser_hand import BrowserHand
from more_core.runtime.hot_reload import ReloadScope


# -- Reasoning Models (v0.6.3) --------------------------------------------


def test_is_reasoning_model_o1():
    assert is_reasoning_model("o1")
    assert is_reasoning_model("o1-mini")
    assert is_reasoning_model("o3")
    assert is_reasoning_model("o4-mini")


def test_is_reasoning_model_deepseek():
    assert is_reasoning_model("deepseek-reasoner")
    assert is_reasoning_model("deepseek-r1")


def test_is_reasoning_model_qwq():
    assert is_reasoning_model("qwq-32b")


def test_not_reasoning_model():
    assert not is_reasoning_model("gpt-4o")
    assert not is_reasoning_model("claude-3-opus")
    assert not is_reasoning_model("llama-3.3-70b")


def test_supports_budget_tokens():
    assert supports_budget_tokens("o1")
    assert supports_budget_tokens("o4-mini")
    assert supports_budget_tokens("deepseek-reasoner")
    assert not supports_budget_tokens("gpt-4o")


def test_get_reasoning_params_openai():
    params = get_reasoning_params("o4-mini")
    assert "max_completion_tokens" in params
    assert "reasoning" in params


def test_get_reasoning_params_claude():
    params = get_reasoning_params("claude-sonnet-4-20250514")
    assert "thinking" in params
    assert params["thinking"]["type"] == "enabled"
    assert "budget_tokens" in params["thinking"]


def test_reasoning_distilled_local_model():
    # 本地推理蒸馏 (LM Studio) — 名字含 claude 但不应走 claude thinking 分支
    model = "qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled"
    assert is_reasoning_model(model)
    params = get_reasoning_params(model)
    assert params.get("enable_thinking") is True
    assert "thinking" not in params  # 不走 claude 分支


def test_get_reasoning_params_normal_model():
    params = get_reasoning_params("gpt-4o")
    assert params == {}


def test_reasoning_router_should_use():
    router = ReasoningRouter()
    assert router.should_use_reasoning(0.8, 100)
    assert router.should_use_reasoning(0.5, 3000)
    assert not router.should_use_reasoning(0.3, 100)


def test_reasoning_router_update_config():
    router = ReasoningRouter()
    router.update_config(budget_tokens=16384)
    assert router.config.budget_tokens == 16384


# -- Model Aliases (v0.6.4) -----------------------------------------------


def test_alias_registry_defaults():
    reg = ModelAliasRegistry()
    assert len(reg.list_aliases()) > 0
    free = reg.list_free()
    assert len(free) >= 5
    assert all(a.free for a in free)


def test_alias_resolve():
    reg = ModelAliasRegistry()
    alias = reg.resolve("free-coder")
    assert alias is not None
    assert alias.provider == "openrouter"
    assert alias.free


def test_alias_resolve_standard():
    reg = ModelAliasRegistry()
    fast = reg.resolve("fast")
    assert fast is not None
    assert fast.provider == "groq"


def test_alias_resolve_unknown():
    reg = ModelAliasRegistry()
    assert reg.resolve("nonexistent") is None


def test_alias_register_custom():
    reg = ModelAliasRegistry()
    reg.register(ModelAlias(alias="my-model", provider="custom", model="test-1"))
    assert reg.resolve("my-model") is not None


def test_alias_api_dict():
    reg = ModelAliasRegistry()
    data = reg.to_api_dict()
    assert isinstance(data, list)
    assert all("alias" in d for d in data)


# -- Channel Reconnect (v0.6.7) -------------------------------------------


def test_reconnect_config_defaults():
    cfg = ReconnectConfig()
    assert cfg.max_retries == 10
    assert cfg.backoff_factor == 2.0
    assert cfg.jitter == 0.3


def test_reconnect_manager_register():
    mgr = ReconnectManager()
    mgr.register("test", None)
    assert mgr.stats()["monitored_channels"] == 1


def test_reconnect_manager_unregister():
    mgr = ReconnectManager()
    mgr.register("test", None)
    mgr.unregister("test")
    assert mgr.stats()["monitored_channels"] == 0


def test_reconnect_state():
    state = ReconnectState(channel_name="discord")
    assert state.connected
    assert state.attempt == 0


# -- Media Support (v0.6.6) -----------------------------------------------


def test_message_with_attachments():
    msg = Message(
        id="1",
        platform="discord",
        chat_id="ch1",
        user_id="u1",
        user_name="test",
        content="see this image",
        timestamp=time.time(),
        attachments=[
            MediaAttachment(
                type=MediaType.IMAGE,
                url="https://example.com/img.png",
                filename="img.png",
                mime_type="image/png",
            ),
        ],
    )
    assert len(msg.attachments) == 1
    assert msg.attachments[0].type == MediaType.IMAGE


def test_response_with_attachments():
    resp = Response(
        content="Here's the file",
        chat_id="ch1",
        attachments=[
            MediaAttachment(type=MediaType.FILE, filename="report.pdf", size_bytes=1024),
        ],
    )
    assert len(resp.attachments) == 1
    assert resp.attachments[0].filename == "report.pdf"


def test_message_thread_and_reply():
    msg = Message(
        id="2",
        platform="slack",
        chat_id="ch1",
        user_id="u1",
        user_name="bob",
        content="reply",
        timestamp=time.time(),
        reply_to="1",
        thread_id="thread-abc",
    )
    assert msg.reply_to == "1"
    assert msg.thread_id == "thread-abc"


# -- Browser Hand (v0.6.4) ------------------------------------------------


def test_browser_hand_manifest():
    h = BrowserHand()
    m = h.manifest
    assert m.id == "browser"
    assert m.category == "automation"
    assert "navigate" in m.approval_actions


@pytest.mark.asyncio
async def test_browser_hand_no_url():
    h = BrowserHand()
    await h.activate()
    result = await h.run({"action": "navigate", "url": ""})
    assert not result.success
    assert "No URL" in result.error
    await h.deactivate()


@pytest.mark.asyncio
async def test_browser_hand_unknown_action():
    h = BrowserHand()
    await h.activate()
    result = await h.run({"action": "fly"})
    assert not result.success
    assert "Unknown action" in result.error
    await h.deactivate()


# -- Hand Persistence (v0.6.5) --------------------------------------------


def test_hand_snapshot_roundtrip(tmp_path):
    persistence = HandPersistence(state_dir=str(tmp_path))
    from more_core.hands.builtins import ResearcherHand

    hand = ResearcherHand()
    hand._run_count = 42
    hand._total_tokens = 1000

    snapshot = persistence.save(hand)
    assert snapshot.hand_id == "researcher"
    assert snapshot.run_count == 42

    loaded = persistence.load("researcher")
    assert loaded is not None
    assert loaded.run_count == 42
    assert loaded.total_tokens == 1000


def test_hand_persistence_list(tmp_path):
    persistence = HandPersistence(state_dir=str(tmp_path))
    from more_core.hands.builtins import ResearcherHand

    hand = ResearcherHand()
    persistence.save(hand)
    assert "researcher" in persistence.list_saved()


def test_hand_persistence_delete(tmp_path):
    persistence = HandPersistence(state_dir=str(tmp_path))
    from more_core.hands.builtins import ResearcherHand

    persistence.save(ResearcherHand())
    assert persistence.delete("researcher")
    assert not persistence.exists("researcher")


# -- Hot-Reload Scopes (v0.6.3) -------------------------------------------


def test_reload_scope_values():
    assert ReloadScope.CONFIG.value == "config"
    assert ReloadScope.LLM_PROVIDERS.value == "llm_providers"
    assert ReloadScope.HANDS.value == "hands"
    assert len(ReloadScope) == 8
