"""Skill 执行增强测试（错误隔离 / 超时 / 真实指标 / 遥测）。

背景：原 ``SkillManager.execute`` 不做异常隔离、不统计 usage/success/avg_duration，
``on_error`` 钩子从未被调用 —— 元数据字段恒为初值（看板假数据）。
"""

from __future__ import annotations

import asyncio

import pytest

from more_core.governance import observability as obs
from more_core.skills.base import (
    Skill,
    SkillCategory,
    SkillManager,
    SkillMetadata,
    SkillResult,
)


class _FakeSkill(Skill):
    def __init__(
        self,
        sid: str = "s1",
        *,
        category: SkillCategory = SkillCategory.CODE,
        result: SkillResult | None = None,
        exc: Exception | None = None,
        delay: float = 0.0,
        valid: bool = True,
    ) -> None:
        super().__init__()
        self._md = SkillMetadata(id=sid, name=sid, description="d", category=category)
        self._result = result if result is not None else SkillResult(success=True, output="ok")
        self._exc = exc
        self._delay = delay
        self._valid = valid

    @property
    def metadata(self) -> SkillMetadata:
        return self._md

    async def validate(self, params: dict) -> tuple[bool, str]:
        return (self._valid, "" if self._valid else "bad params")

    async def execute(self, params: dict):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc:
            raise self._exc
        return self._result


@pytest.mark.asyncio
async def test_metrics_updated_on_success():
    mgr = SkillManager()
    skill = _FakeSkill()
    mgr.register(skill)

    await mgr.execute("s1", {})
    await mgr.execute("s1", {})

    assert skill.metadata.usage_count == 2
    assert skill.metadata.success_rate == 1.0
    assert skill.metadata.avg_duration_ms > 0


@pytest.mark.asyncio
async def test_metrics_track_failures():
    mgr = SkillManager()
    skill = _FakeSkill(result=SkillResult(success=False, error="boom"))
    mgr.register(skill)

    await mgr.execute("s1", {})
    await mgr.execute("s1", {})

    assert skill.metadata.usage_count == 2
    assert skill.metadata.success_rate == 0.0


@pytest.mark.asyncio
async def test_exception_is_isolated_and_on_error_fires():
    mgr = SkillManager()
    mgr.register(_FakeSkill(exc=RuntimeError("kaboom")))
    seen: list[str] = []

    async def on_error(skill_id, params, result):
        seen.append(result.error or "")

    mgr.add_hook("on_error", on_error)

    result = await mgr.execute("s1", {})  # 不得抛异常
    assert result.success is False
    assert "kaboom" in (result.error or "")
    assert "RuntimeError" in (result.error or "")
    assert seen and "kaboom" in seen[0]


@pytest.mark.asyncio
async def test_timeout_returns_structured_failure():
    mgr = SkillManager(timeout_s=0.1)
    mgr.register(_FakeSkill(delay=2.0))

    result = await mgr.execute("s1", {})
    assert result.success is False
    assert "timed out" in (result.error or "")
    assert 0 < result.duration_ms < 1000


@pytest.mark.asyncio
async def test_non_skillresult_return_is_rejected():
    skill = _FakeSkill()
    skill._result = "not a SkillResult"  # type: ignore[assignment]
    mgr = SkillManager()
    mgr.register(skill)

    result = await mgr.execute("s1", {})
    assert result.success is False
    assert "expected SkillResult" in (result.error or "")


@pytest.mark.asyncio
async def test_validation_failure_is_recorded():
    mgr = SkillManager()
    skill = _FakeSkill(valid=False)
    mgr.register(skill)

    result = await mgr.execute("s1", {})
    assert result.success is False
    assert "Validation failed" in (result.error or "")
    assert skill.metadata.usage_count == 1


@pytest.mark.asyncio
async def test_execution_is_telemetered():
    mgr = SkillManager()
    mgr.register(_FakeSkill())
    await mgr.execute("s1", {})

    st = obs.query_skill_stats(3600)
    assert st["runs"] == 1
    assert st["success_rate"] == 1.0
    assert st["by_skill"]["s1"]["calls"] == 1
    assert st["by_category"]["code"]["calls"] == 1


def test_registry_stats_include_runs():
    mgr = SkillManager()
    mgr.register(_FakeSkill())
    assert mgr.get_stats()["total_runs"] == 0
    assert mgr.get_stats()["success_rate"] == 0.0


def test_duplicate_registration_does_not_duplicate_category():
    mgr = SkillManager()
    mgr.register(_FakeSkill(sid="dup"))
    mgr.register(_FakeSkill(sid="dup"))
    assert mgr.get_stats()["by_category"]["code"] == 1


def test_unknown_skill_returns_structured_error():
    mgr = SkillManager()
    result = asyncio.run(mgr.execute("nope", {}))
    assert result.success is False
    assert "Skill not found" in (result.error or "")


def test_skills_metrics_endpoint(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        obs.record_skill_run(skill_id="s1", category="code", success=True, duration_ms=12.5)
        resp = client.get("/api/v1/metrics/skills?window_s=3600")
    assert resp.status_code == 200
    body = resp.json()
    assert body["metrics"]["runs"] == 1
    assert body["metrics"]["success_rate"] == 1.0
    assert "total_skills" in body["registry"]


def test_skill_list_and_detail_endpoints(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        body = client.get("/api/v1/skills").json()
        skills = body["skills"]
        assert skills, "默认技能应已注册"
        for s in skills:
            assert {"status", "usage_count", "success_rate", "avg_duration_ms"} <= set(s)
        sid = skills[0]["id"]
        detail = client.get(f"/api/v1/skills/{sid}")
        assert detail.status_code == 200
        assert "healthy" in detail.json()["skill"]
        assert client.get("/api/v1/skills/definitely-not-a-skill").status_code == 404


@pytest.mark.asyncio
async def test_start_all_activates_and_isolates_failures():
    mgr = SkillManager()
    good = _FakeSkill(sid="good")
    bad = _FakeSkill(sid="bad")

    async def _boom() -> None:
        raise RuntimeError("start failed")

    bad.start = _boom  # type: ignore[method-assign]

    mgr.register(good)
    mgr.register(bad)
    await mgr.start_all()  # 不得因 bad 抛异常

    assert good.get_status().value == "active"
    assert bad.get_status().value != "active"


@pytest.mark.asyncio
async def test_core_start_activates_default_skills(core):
    """回归：注册 ≠ 可用。启动后默认技能应处于 ACTIVE（此前全 INACTIVE）。"""
    await core.start()
    stats = core.skill_manager.get_stats()
    assert stats["total_skills"] >= 1
    assert stats["active"] == stats["total_skills"]
