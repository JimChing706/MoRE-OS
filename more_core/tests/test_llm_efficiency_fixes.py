"""生产效率修复回归：思考预算守卫口径 + LLM 链路预检。"""

from __future__ import annotations

import pytest

from more_core.llm.manager import LLMManager
from more_core.llm.preflight import preflight_llm
from more_core.llm.provider import LLMRequest, LLMResponse


@pytest.fixture()
def manager():
    return LLMManager(providers=[], fallback_chain=[])


def _resp(content: str, completion_tokens: int, reasoning: str = "") -> LLMResponse:
    return LLMResponse(
        content=content,
        provider="p",
        model="m",
        prompt_tokens=100,
        completion_tokens=completion_tokens,
        latency_ms=10.0,
        reasoning_content=reasoning or None,
    )


# ---------------------------------------------------------------------------
# 思考预算守卫：不得误杀"本来就短"的合法答案
# ---------------------------------------------------------------------------


def test_short_answer_with_reasoning_is_accepted(manager):
    """生产事故：max_tokens=2048 + 回答 47 token + 有 reasoning → 旧判据误杀。"""
    req = LLMRequest(prompt="写个函数", max_tokens=2048, enable_thinking=True)
    out = manager._postprocess_llm_response(
        _resp("```python\ndef f(x):\n    return x\n```", 47, reasoning="思考" * 200), req
    )
    assert out.content


def test_short_plain_answer_is_accepted(manager):
    req = LLMRequest(prompt="print", max_tokens=2048)
    out = manager._postprocess_llm_response(_resp("print(1)", 5), req)
    assert out.content == "print(1)"


def test_empty_answer_with_heavy_thinking_is_rejected(manager):
    """真实故障模式：思考吃掉预算、答案为空 → 必须拦截。"""
    from more_core.core.errors import MoREError

    req = LLMRequest(prompt="写个函数", max_tokens=2048, enable_thinking=True)
    with pytest.raises(MoREError):
        manager._postprocess_llm_response(_resp("", 500, reasoning="x" * 4000), req)


def test_empty_content_with_tokens_is_rejected(manager):
    from more_core.core.errors import MoREError

    req = LLMRequest(prompt="写个函数", max_tokens=256)
    with pytest.raises(MoREError):
        manager._postprocess_llm_response(_resp("   ", 30), req)


# ---------------------------------------------------------------------------
# LLM 链路预检：模型名写错 / 兜底链断裂必须告警
# ---------------------------------------------------------------------------


class _FakeProvider:
    def __init__(self, base: str, model: str) -> None:
        self._base = base
        self.model = model

    async def health(self) -> bool:
        return True


class _FakeLLM:
    def __init__(self, providers: dict, fallback: list[str]) -> None:
        self._providers = providers
        self._fallback = fallback

    def list_providers(self) -> list[str]:
        return list(self._providers)


class _FakeState:
    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model


class _FakeStateMgr:
    def __init__(self, provider: str, model: str) -> None:
        self._s = _FakeState(provider, model)

    def get_state(self) -> _FakeState:
        return self._s


@pytest.mark.asyncio
async def test_preflight_flags_missing_model(monkeypatch):
    llm = _FakeLLM({"lmstudio": _FakeProvider("http://x/v1", "local-model")}, ["lmstudio"])

    async def _models(url: str):
        assert url.endswith("/models")
        return ["ornith-1.5-35b-a3b", "ornith-ai/ornith-1.5-9b"]

    monkeypatch.setattr("more_core.llm.preflight._fetch_models", _models)
    report = await preflight_llm(llm, ["lmstudio"])
    assert report.ok is False
    assert any("local-model" in w and "not found" in w for w in report.warnings)
    assert report.degraded is True  # 只有一个 provider → 兜底不足


@pytest.mark.asyncio
async def test_preflight_passes_with_valid_model_and_full_chain(monkeypatch):
    llm = _FakeLLM(
        {
            "lmstudio": _FakeProvider("http://x/v1", "ornith-1.5-35b-a3b"),
            "ollama": _FakeProvider("http://y", "qwen2.5:7b"),
        },
        ["lmstudio", "ollama"],
    )

    async def _models(url: str):
        if "11434" in url or url.endswith("/api/tags"):
            return ["qwen2.5:7b"]
        return ["ornith-1.5-35b-a3b"]

    monkeypatch.setattr("more_core.llm.preflight._fetch_models", _models)
    # 契约强化：预检同时校验 state manager 的"生效模型"（配置漂移会 400）。
    # 本用例要验证全绿，故把生效模型对齐为服务端确实存在的模型。
    monkeypatch.setattr(
        "more_core.llm.state_manager.get_llm_state_manager",
        lambda: _FakeStateMgr("lmstudio", "ornith-1.5-35b-a3b"),
    )
    report = await preflight_llm(llm, ["lmstudio", "ollama"])
    assert report.ok is True
    assert report.state_model_present is True
    assert report.degraded is False
    assert report.chain_registered == ["lmstudio", "ollama"]


@pytest.mark.asyncio
async def test_preflight_flags_unregistered_chain_provider(monkeypatch):
    """生产事故：声明了 ollama 兜底但 provider 未注册 → 必须告警。"""
    llm = _FakeLLM(
        {"lmstudio": _FakeProvider("http://x/v1", "ornith-1.5-35b-a3b")}, ["lmstudio", "ollama"]
    )

    async def _models(url: str):
        return ["ornith-1.5-35b-a3b"]

    monkeypatch.setattr("more_core.llm.preflight._fetch_models", _models)
    report = await preflight_llm(llm, ["lmstudio", "ollama"])
    assert report.degraded is True
    assert any("degraded" in w for w in report.warnings)


@pytest.mark.asyncio
async def test_preflight_warns_when_no_provider():
    report = await preflight_llm(_FakeLLM({}, []), [])
    assert report.ok is False
    assert any("no LLM provider" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# ZEN-19 子串误判回归：正常函数名不得被判为"禁止操作"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "实现 normalize_email(e) 规范化邮箱",
        "实现 format_string(s) 格式化",
        "解析 mkfs_parser 配置",
        "写一个 formatting helper",
    ],
)
def test_zen19_allows_benign_substrings(query):
    from more_core.zen_rules import _check_absolute_prohibition

    assert _check_absolute_prohibition({"query": query}) is True


@pytest.mark.parametrize(
    "query",
    [
        "执行 rm -rf /tmp/x",
        "run rm file.txt",
        "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/sda",
        "echo hi > /dev/sda",
    ],
)
def test_zen19_still_blocks_real_forbidden_ops(query):
    from more_core.zen_rules import _check_absolute_prohibition

    assert _check_absolute_prohibition({"query": query}) is False
