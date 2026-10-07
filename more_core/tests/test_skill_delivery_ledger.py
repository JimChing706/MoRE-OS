"""技能交付台账测试（归档 / 完整性 / 验收状态 / 可追溯）。

对应收尾要求：全部技能的核心信息（名称/描述/版本/依赖/部署/责任人）标准化录入，
状态标识为"已验收"，并可通过 API 追溯。
"""

from __future__ import annotations

import pytest

from more_core.skills import create_default_skill_manager
from more_core.skills.base import SkillCategory, SkillMetadata
from more_core.skills.delivery import (
    STATUS_ACCEPTED,
    STATUS_DRAFT,
    SkillDeliveryLedger,
    archive_skill_manager,
    get_default_skill_ledger,
)


def _meta(sid: str = "t.skill", **over: object) -> SkillMetadata:
    base = dict(
        id=sid,
        name="Demo",
        description="demo skill",
        category=SkillCategory.TOOLS,
        version="1.0.0",
        dependencies=["httpx"],
        maintainer="Team A",
        deployment={"runtime": "python>=3.10", "network_egress": True},
        config_schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    )
    base.update(over)
    return SkillMetadata(**base)  # type: ignore[arg-type]


@pytest.fixture()
def ledger(tmp_path) -> SkillDeliveryLedger:
    return SkillDeliveryLedger(tmp_path / "sd.db")


def test_archive_and_get(ledger):
    assert ledger.archive(_meta(), status=STATUS_ACCEPTED) is True
    rec = ledger.get("t.skill")
    assert rec is not None
    assert rec.name == "Demo"
    assert rec.version == "1.0.0"
    assert rec.maintainer == "Team A"
    assert rec.dependencies == ["httpx"]
    assert rec.deployment["network_egress"] is True
    assert rec.accepted is True
    assert rec.complete is True


def test_archive_is_upsert_and_keeps_archived_at(ledger):
    ledger.archive(_meta(version="1.0.0"))
    first = ledger.get("t.skill")
    assert first is not None

    ledger.archive(_meta(version="2.0.0"), status=STATUS_ACCEPTED)
    second = ledger.get("t.skill")
    assert second is not None
    assert second.version == "2.0.0"
    assert second.archived_at == pytest.approx(first.archived_at)
    assert second.updated_at >= first.updated_at
    assert len(ledger.list()) == 1, "重复归档不得产生重复记录"


def test_mark_accepted(ledger):
    ledger.archive(_meta(), status=STATUS_DRAFT)
    assert ledger.get("t.skill").accepted is False  # type: ignore[union-attr]
    assert ledger.mark_accepted("t.skill") is True
    assert ledger.get("t.skill").accepted is True  # type: ignore[union-attr]
    assert ledger.mark_accepted("missing") is False


def test_incomplete_record_is_flagged(ledger):
    ledger.archive(_meta(description=""))
    rec = ledger.get("t.skill")
    assert rec is not None and rec.complete is False
    assert ledger.stats()["incomplete"] == ["t.skill"]


def test_stats_rates(ledger):
    ledger.archive(_meta("a"), status=STATUS_ACCEPTED)
    ledger.archive(_meta("b"), status=STATUS_DRAFT)
    ledger.archive(_meta("c", maintainer=""), status=STATUS_ACCEPTED)

    st = ledger.stats()
    assert st["total"] == 3
    assert st["accepted"] == 2
    assert st["complete"] == 2
    assert st["acceptance_rate"] == pytest.approx(0.667, abs=1e-3)
    assert st["by_status"]["accepted"] == 2
    assert st["by_status"]["draft"] == 1


def test_archive_skill_manager_covers_all_default_skills():
    mgr = create_default_skill_manager()
    count = archive_skill_manager(mgr)
    ledger = get_default_skill_ledger()

    assert count == len(mgr.list_skills()) == 5
    records = {r.skill_id: r for r in ledger.list()}
    assert set(records) == {"web.search", "web.browse", "code.execute", "data.analyze", "api.call"}
    for sid, rec in records.items():
        assert rec.accepted, sid
        assert rec.complete, sid
        assert rec.config_schema, f"{sid} 台账缺少 config_schema"
        assert rec.deployment, f"{sid} 台账缺少部署要求"


# ---------------------------------------------------------------------------
# API 追溯
# ---------------------------------------------------------------------------


def test_skill_delivery_endpoints(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        stats = client.get("/api/v1/skill-delivery/stats").json()["stats"]
        assert stats["total"] >= 5
        assert stats["acceptance_rate"] == 1.0
        assert stats["incomplete"] == []

        listing = client.get("/api/v1/skill-delivery").json()
        assert listing["count"] == stats["total"]
        sid = listing["deliverables"][0]["skill_id"]

        detail = client.get(f"/api/v1/skill-delivery/{sid}").json()["deliverable"]
        assert detail["accepted"] is True
        assert detail["complete"] is True
        assert client.get("/api/v1/skill-delivery/nope").status_code == 404

        synced = client.post("/api/v1/skill-delivery/sync").json()
        assert synced["archived"] >= 5
