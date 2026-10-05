"""渠道适配器测试（qq/telegram/wechat/discord/webhook）。

顺带修复 D-17：适配器此前**无法用自身配置构造**（ChannelConfig(**config) → TypeError）。
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from more_core.channels.base import ChannelType, Response
from more_core.channels.discord_adapter import DiscordAdapter
from more_core.channels.qq_adapter import QQAdapter
from more_core.channels.telegram_adapter import TelegramAdapter
from more_core.channels.webhook_adapter import WebhookAdapter, WebhookMethod
from more_core.channels.wechat_adapter import WeChatAdapter


# ---------------------------------------------------------------------------
# D-17：构造契约
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls,extra_cfg,probe",
    [
        (WebhookAdapter, {"url": "http://x/h", "secret": "s"}, lambda a: a._url == "http://x/h"),
        (QQAdapter, {"port": 5701, "access_token": "t"}, lambda a: a._port == 5701),
        (TelegramAdapter, {"bot_token": "tb"}, lambda a: "tb" in a._api_base),
        (WeChatAdapter, {"corp_id": "c", "secret": "s"}, lambda a: a._corp_id == "c"),
        (DiscordAdapter, {"bot_token": "d", "guild_id": "g"}, lambda a: a._guild_id == "g"),
    ],
)
def test_adapters_construct_with_platform_specific_config(cls, extra_cfg, probe):
    """回归 D-17：平台专有键此前直接触发 TypeError，导致适配器无法用真实配置构造。"""
    adapter = cls({"channel_type": ChannelType.WEBHOOK, **extra_cfg})
    assert probe(adapter) is True
    # ChannelConfig 已有一等字段（如 bot_token）落到 config 属性；
    # 其余平台专有键收进 config.extra 便于下游消费。
    first_class = {"bot_token", "webhook_url", "enabled", "channel_type"}
    for key in extra_cfg:
        if key in first_class:
            assert getattr(adapter.config, key) == extra_cfg[key]
        else:
            assert key in adapter.config.extra


def test_platform_names():
    assert WebhookAdapter({"channel_type": ChannelType.WEBHOOK}).platform_name == "webhook"
    assert QQAdapter({"channel_type": ChannelType.WEBHOOK}).platform_name == "qq"
    assert TelegramAdapter({"channel_type": ChannelType.WEBHOOK}).platform_name == "telegram"
    assert WeChatAdapter({"channel_type": ChannelType.WEBHOOK}).platform_name == "wechat"
    assert DiscordAdapter({"channel_type": ChannelType.WEBHOOK}).platform_name == "discord"


# ---------------------------------------------------------------------------
# webhook（深度）
# ---------------------------------------------------------------------------


def _webhook(**over) -> WebhookAdapter:
    cfg = {"channel_type": ChannelType.WEBHOOK, "url": "http://hook.test/p", "timeout": 5}
    cfg.update(over)
    return WebhookAdapter(cfg)


def _resp(content="hi", chat_id="c1") -> Response:
    return Response(content=content, chat_id=chat_id)


@pytest.mark.asyncio
async def test_webhook_start_stop():
    a = _webhook()
    await a.start()
    assert a._running is True and a._session is not None
    await a.stop()
    assert a._running is False


def test_webhook_signature_is_hmac_sha256_and_deterministic():
    a = _webhook(secret="topsecret")
    expected = __import__("hmac").new(b"topsecret", b"payload", hashlib.sha256).hexdigest()
    assert a._generate_signature("payload") == expected
    assert a._generate_signature("payload") == a._generate_signature("payload")


def test_webhook_signature_empty_without_secret():
    assert _webhook()._generate_signature("x") == ""


@pytest.mark.asyncio
async def test_webhook_send_success_updates_stats():
    a = _webhook()
    a._session = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert await a.send_message(_resp()) is True
    assert a.get_stats()["sent"] == 1 and a.get_stats()["failed"] == 0


@pytest.mark.asyncio
async def test_webhook_send_failure_counts():
    a = _webhook()
    a._session = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert await a.send_message(_resp()) is False
    assert a.get_stats()["failed"] == 1


@pytest.mark.asyncio
async def test_webhook_send_exception_is_caught():
    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no")

    a = _webhook()
    a._session = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    assert await a.send_message(_resp()) is False
    assert a.get_stats()["failed"] == 1


@pytest.mark.asyncio
async def test_webhook_send_attaches_signature_header():
    seen: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["sig"] = r.headers.get("X-Signature")
        seen["body"] = r.content
        return httpx.Response(204)

    a = _webhook(secret="s3cr3t")
    a._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await a.send_message(_resp()) is True
    assert seen["sig"] and len(seen["sig"]) == 64


@pytest.mark.asyncio
async def test_webhook_send_to_user_sets_direct_metadata():
    captured: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        captured["body"] = r.content.decode()
        return httpx.Response(200)

    a = _webhook()
    a._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await a.send_message_to_user("hey", "u1") is True
    assert '"type": "direct"' in captured["body"] or '"type":"direct"' in captured["body"]


@pytest.mark.asyncio
async def test_webhook_health_check_paths():
    a = _webhook()
    a._session = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    assert await a.health_check() is True

    bad = _webhook()
    bad._session = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    assert await bad.health_check() is False

    nourl = WebhookAdapter({"channel_type": ChannelType.WEBHOOK})
    nourl._session = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    assert await nourl.health_check() is False


def test_webhook_method_enum_default():
    assert _webhook()._method == WebhookMethod.POST


# ---------------------------------------------------------------------------
# wechat / qq / telegram / discord（关键路径）
# ---------------------------------------------------------------------------


def test_wechat_verify_signature():
    a = WeChatAdapter({"channel_type": ChannelType.WEBHOOK, "token": "tok"})
    ts, nonce = "123", "abc"
    expected = hashlib.sha1("".join(sorted(["tok", ts, nonce])).encode()).hexdigest()
    assert a.verify_signature(expected, ts, nonce) is True
    assert a.verify_signature("wrong", ts, nonce) is False
    # 无 token → 放行（不校验）
    assert WeChatAdapter({"channel_type": ChannelType.WEBHOOK}).verify_signature("x", "1", "2") is True


@pytest.mark.asyncio
async def test_wechat_send_without_config_returns_false():
    a = WeChatAdapter({"channel_type": ChannelType.WEBHOOK})
    assert await a.send_message(_resp()) is False


@pytest.mark.asyncio
async def test_qq_send_routes_by_chat_id_prefix():
    a = QQAdapter({"channel_type": ChannelType.WEBHOOK})
    calls: list[tuple] = []
    a._send_group_message = lambda gid, content: calls.append(("group", gid, content)) or _true()
    a._send_private_message = lambda uid, content: calls.append(("user", uid, content)) or _true()

    await a.send_message(Response(content="m", chat_id="group_42"))
    await a.send_message(Response(content="m", chat_id="user_7"))
    assert calls[0] == ("group", 42, "m")
    assert calls[1] == ("user", 7, "m")


def _true():
    async def _c():
        return True

    return _c()


@pytest.mark.asyncio
async def test_telegram_send_uses_call_api(monkeypatch):
    a = TelegramAdapter({"channel_type": ChannelType.WEBHOOK, "bot_token": "tb"})
    seen: dict = {}

    async def fake_call(method, params=None):
        seen["method"], seen["params"] = method, params
        return {"ok": True}

    monkeypatch.setattr(a, "_call_api", fake_call)
    assert await a.send_message(_resp(content="hello", chat_id="c")) is True
    assert seen["method"] == "sendMessage"
    assert seen["params"]["text"] == "hello"


@pytest.mark.asyncio
async def test_discord_send_uses_call_api(monkeypatch):
    a = DiscordAdapter({"channel_type": ChannelType.WEBHOOK, "bot_token": "d"})

    async def fake_call(method, path, payload=None):
        return {"id": "msg1"} if "messages" in path else {}

    monkeypatch.setattr(a, "_call_api", fake_call)
    assert await a.send_message(_resp(chat_id="123")) is True
