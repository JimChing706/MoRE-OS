"""Skills module - 前沿技术技能包系统."""

from .base import (
    Skill,
    SkillCategory,
    SkillManager,
    SkillMetadata,
    SkillResult,
    SkillStatus,
)
from .code_skills import APICallSkill, CodeExecutionSkill, DataAnalysisSkill
from .web_skills import WebBrowseSkill, WebSearchSkill

__all__ = [
    "APICallSkill",
    "CodeExecutionSkill",
    "DataAnalysisSkill",
    "Skill",
    "SkillCategory",
    "SkillManager",
    "SkillMetadata",
    "SkillResult",
    "SkillStatus",
    "WebBrowseSkill",
    "WebSearchSkill",
]


def create_default_skill_manager() -> SkillManager:
    """Create skill manager with default skills."""
    manager = SkillManager()

    manager.register(WebSearchSkill())
    manager.register(WebBrowseSkill())
    manager.register(CodeExecutionSkill())
    manager.register(DataAnalysisSkill())
    manager.register(APICallSkill())

    return manager
