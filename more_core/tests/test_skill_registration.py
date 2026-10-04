"""Regression: default skills must be registered at bootstrap and hot-reload.

v0.9.9 rewired bootstrap/hot-reload to construct a bare ``SkillManager()``,
leaving the runtime skill registry empty — ``GET /api/v1/skills`` always
returned ``[]`` even though ``create_default_skill_manager`` existed. These
tests pin the factory contents and the bootstrap wiring.
"""

from __future__ import annotations

from more_core.core.config import Settings
from more_core.runtime.bootstrap import init_services
from more_core.skills import create_default_skill_manager

EXPECTED_DEFAULT_SKILL_IDS = {
    "web.search",
    "web.browse",
    "code.execute",
    "data.analyze",
    "api.call",
}


def test_default_skill_manager_registers_all_builtins() -> None:
    manager = create_default_skill_manager()
    ids = {s.id for s in manager.list_skills()}
    assert ids == EXPECTED_DEFAULT_SKILL_IDS


def test_bootstrap_registers_default_skills() -> None:
    services = init_services(Settings())
    manager = services["skill_manager"]
    ids = {s.id for s in manager.list_skills()}
    assert ids == EXPECTED_DEFAULT_SKILL_IDS
