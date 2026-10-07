"""热重载测试（runtime/hot_reload.py 覆盖补齐）。"""

from __future__ import annotations

import pytest

from more_core.runtime.hot_reload import HotReloader, ReloadEvent, ReloadScope


@pytest.fixture()
def reloader(core):
    return HotReloader(core)


# ---------------------------------------------------------------------------
# 调度与去抖
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_success_records_event(reloader):
    event = await reloader.reload(ReloadScope.SECURITY)
    assert isinstance(event, ReloadEvent)
    assert event.success is True and event.scope == ReloadScope.SECURITY
    assert event.duration_ms >= 0
    assert reloader.history()[-1] is event
    assert reloader.stats()["successful"] == 1


@pytest.mark.asyncio
async def test_reload_is_debounced(reloader):
    first = await reloader.reload(ReloadScope.SECURITY)
    assert first.success is True

    second = await reloader.reload(ReloadScope.SECURITY)
    assert second.success is False
    assert "Debounced" in (second.error or "")


@pytest.mark.asyncio
async def test_reload_without_handler(reloader):
    reloader._handlers.pop(ReloadScope.SECURITY)
    event = await reloader.reload(ReloadScope.SECURITY)
    assert event.success is False and "No handler" in (event.error or "")


@pytest.mark.asyncio
async def test_reload_handler_exception_is_captured(reloader):
    async def boom(**_kw):
        raise RuntimeError("handler down")

    reloader._handlers[ReloadScope.SECURITY] = boom
    event = await reloader.reload(ReloadScope.SECURITY)
    assert event.success is False and "handler down" in (event.error or "")
    assert reloader.stats()["failed"] == 1


@pytest.mark.asyncio
async def test_reload_all_covers_every_scope(reloader):
    events = await reloader.reload_all()
    assert len(events) == len(ReloadScope)
    assert {e.scope for e in events} == set(ReloadScope)
    assert all(e.success for e in events), [e.error for e in events if not e.success]


def test_history_limit_and_stats(reloader):
    for i in range(5):
        reloader._history.append(ReloadEvent(scope=ReloadScope.SECURITY, success=i % 2 == 0))
    assert len(reloader.history(limit=2)) == 2
    stats = reloader.stats()
    assert stats["total_reloads"] == 5
    assert stats["successful"] == 3 and stats["failed"] == 2


# ---------------------------------------------------------------------------
# 各 scope 的处理器
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,change_key",
    [
        (ReloadScope.CONFIG, "providers"),
        (ReloadScope.LLM_PROVIDERS, "providers"),
        (ReloadScope.HANDS, "registered"),
        (ReloadScope.SKILLS, "new_skills"),
        (ReloadScope.CHANNELS, "channels"),
        (ReloadScope.COMMANDS, "commands"),
        (ReloadScope.PLUGINS, "plugins"),
        (ReloadScope.SECURITY, "rbac_enabled"),
    ],
)
async def test_each_scope_handler(reloader, scope, change_key):
    event = await reloader.reload(scope)
    assert event.success is True, event.error
    assert change_key in event.changes


@pytest.mark.asyncio
async def test_reload_config_updates_settings(reloader, core):
    old_settings = core.settings
    event = await reloader.reload(ReloadScope.CONFIG)
    assert event.success is True
    assert core.settings is not old_settings  # 已替换为新 Settings


@pytest.mark.asyncio
async def test_reload_skills_rebuilds_manager(reloader, core):
    old_mgr = core.skill_manager
    event = await reloader.reload(ReloadScope.SKILLS)
    assert event.success is True
    assert core.skill_manager is not old_mgr
    assert event.changes["new_skills"] >= 1
