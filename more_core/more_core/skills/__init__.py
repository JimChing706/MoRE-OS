"""Skills module - 前沿技术技能包系统."""

from .base import (
    Skill,
    SkillCategory,
    SkillStatus,
    SkillMetadata,
    SkillResult,
    SkillManager,
)
from .web_skills import WebSearchSkill, WebBrowseSkill
from .code_skills import CodeExecutionSkill, DataAnalysisSkill, APICallSkill

__all__ = [
    "Skill",
    "SkillCategory",
    "SkillStatus",
    "SkillMetadata",
    "SkillResult",
    "SkillManager",
    "WebSearchSkill",
    "WebBrowseSkill",
    "CodeExecutionSkill",
    "DataAnalysisSkill",
    "APICallSkill",
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
