"""Tests for the Hands subsystem."""

import pytest
from more_core.hands.base import Hand, HandManifest, HandResult, HandStatus
from more_core.hands.registry import HandRegistry
from more_core.hands.manager import HandManager
from more_core.hands.builtins import register_builtin_hands, ResearcherHand, CoderHand


class _TestHand(Hand):
    @property
    def manifest(self) -> HandManifest:
        return HandManifest(id="test", name="Test Hand", description="for testing")

    async def execute(self, context):
        return HandResult(hand_id="test", success=True, output="ok")


class _FailHand(Hand):
    @property
    def manifest(self) -> HandManifest:
        return HandManifest(id="fail", name="Fail Hand", description="always fails", timeout_s=5)

    async def execute(self, context):
        raise RuntimeError("boom")


# -- registry ------------------------------------------------------------------

def test_registry_register_and_list():
    reg = HandRegistry()
    h = _TestHand()
    reg.register(type(h), h.manifest)
    assert "test" in reg.list_ids()
    assert reg.get_manifest("test").name == "Test Hand"


def test_registry_unregister():
    reg = HandRegistry()
    h = _TestHand()
    reg.register(type(h), h.manifest)
    reg.unregister("test")
    assert "test" not in reg.list_ids()


def test_builtin_hands_registered():
    reg = HandRegistry()
    register_builtin_hands(reg)
    ids = reg.list_ids()
    assert "researcher" in ids
    assert "coder" in ids
    assert "digest" in ids
    assert "monitor" in ids
    assert reg.stats()["total_hands"] == 4


# -- hand lifecycle ------------------------------------------------------------

@pytest.mark.asyncio
async def test_hand_activate_deactivate():
    h = _TestHand()
    assert h.status == HandStatus.INACTIVE
    await h.activate()
    assert h.status == HandStatus.ACTIVE
    await h.deactivate()
    assert h.status == HandStatus.INACTIVE


@pytest.mark.asyncio
async def test_hand_pause_resume():
    h = _TestHand()
    await h.activate()
    await h.pause()
    assert h.status == HandStatus.PAUSED
    await h.resume()
    assert h.status == HandStatus.ACTIVE
    await h.deactivate()


@pytest.mark.asyncio
async def test_hand_run_success():
    h = _TestHand()
    await h.activate()
    result = await h.run()
    assert result.success
    assert result.output == "ok"
    assert h.stats["run_count"] == 1
    await h.deactivate()


@pytest.mark.asyncio
async def test_hand_run_failure():
    h = _FailHand()
    await h.activate()
    result = await h.run()
    assert not result.success
    assert "boom" in result.error
    await h.deactivate()


# -- manager -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_activate_and_run():
    reg = HandRegistry()
    reg.register(_TestHand, _TestHand().manifest)
    mgr = HandManager(reg)
    hand = await mgr.activate("test")
    assert hand.status == HandStatus.ACTIVE
    result = await mgr.run_once("test")
    assert result.success
    await mgr.deactivate("test")


@pytest.mark.asyncio
async def test_manager_list_active():
    reg = HandRegistry()
    reg.register(_TestHand, _TestHand().manifest)
    mgr = HandManager(reg)
    await mgr.activate("test")
    active = mgr.list_active()
    assert len(active) == 1
    assert active[0]["id"] == "test"
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_manager_duplicate_activate_raises():
    reg = HandRegistry()
    reg.register(_TestHand, _TestHand().manifest)
    mgr = HandManager(reg)
    await mgr.activate("test")
    with pytest.raises(ValueError, match="already active"):
        await mgr.activate("test")
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_manager_unknown_hand_raises():
    reg = HandRegistry()
    mgr = HandManager(reg)
    with pytest.raises(KeyError, match="Unknown Hand"):
        await mgr.activate("nonexistent")
