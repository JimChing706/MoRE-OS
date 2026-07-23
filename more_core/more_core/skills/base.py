"""Skill Package System - 前沿技术技能实现.

参考: Hermes Skills, OpenFang Hands
设计理念: 模块化、可扩展、自包含
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

# Type alias for hook handlers — must be awaitable since execute() awaits them.
HookHandler = Callable[..., Awaitable[Any]]


class SkillCategory(Enum):
    """技能分类."""

    WEB = "web"  # 网页搜索、浏览
    CODE = "code"  # 代码执行、调试
    DATA = "data"  # 数据处理、分析
    API = "api"  # API 调用、集成
    TOOLS = "tools"  # 工具操作
    AUTOMATION = "auto"  # 自动化、定时
    MEMORY = "memory"  # 记忆、知识
    SECURITY = "security"  # 安全相关


class SkillStatus(Enum):
    """技能状态."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    UPDATING = "updating"


@dataclass
class SkillMetadata:
    """技能元数据."""

    id: str
    name: str
    description: str
    category: SkillCategory
    version: str = "1.0.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)
    usage_count: int = 0
    success_rate: float = 1.0
    avg_duration_ms: float = 0


@dataclass
class SkillResult:
    """技能执行结果."""

    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)


SkillExecutor = Callable[..., Awaitable[SkillResult]]


class Skill(ABC):
    """技能基类."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._metadata: SkillMetadata | None = None
        self._status = SkillStatus.INACTIVE
        self._executor: SkillExecutor | None = None

    @property
    @abstractmethod
    def metadata(self) -> SkillMetadata:
        """返回技能元数据."""
        pass

    @abstractmethod
    async def execute(self, params: dict[str, Any]) -> SkillResult:
        """执行技能."""
        pass

    @abstractmethod
    async def validate(self, params: dict[str, Any]) -> tuple[bool, str]:
        """验证参数."""
        pass

    async def start(self) -> None:
        """启动技能."""
        self._status = SkillStatus.ACTIVE

    async def stop(self) -> None:
        """停止技能."""
        self._status = SkillStatus.INACTIVE

    async def health_check(self) -> bool:
        """健康检查."""
        return self._status == SkillStatus.ACTIVE

    def get_status(self) -> SkillStatus:
        """获取状态."""
        return self._status


class SkillManager:
    """技能管理器."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._categories: dict[SkillCategory, list[str]] = {c: [] for c in SkillCategory}
        self._hooks: dict[str, list[HookHandler]] = {
            "before_execute": [],
            "after_execute": [],
            "on_error": [],
        }

    def register(self, skill: Skill) -> None:
        """注册技能."""
        self._skills[skill.metadata.id] = skill
        self._categories[skill.metadata.category].append(skill.metadata.id)

    def unregister(self, skill_id: str) -> None:
        """注销技能."""
        skill = self._skills.pop(skill_id, None)
        if skill:
            cat = skill.metadata.category
            if skill_id in self._categories[cat]:
                self._categories[cat].remove(skill_id)

    def get(self, skill_id: str) -> Skill | None:
        """获取技能."""
        return self._skills.get(skill_id)

    def list_skills(self, category: SkillCategory | None = None) -> list[SkillMetadata]:
        """列出技能."""
        if category:
            return [self._skills[sid].metadata for sid in self._categories[category]]
        return [s.metadata for s in self._skills.values()]

    async def execute(self, skill_id: str, params: dict[str, Any]) -> SkillResult:
        """执行技能 (带钩子)."""
        skill = self._skills.get(skill_id)
        if not skill:
            return SkillResult(success=False, error=f"Skill not found: {skill_id}")

        for hook in self._hooks["before_execute"]:
            await hook(skill_id, params)

        valid, msg = await skill.validate(params)
        if not valid:
            return SkillResult(success=False, error=f"Validation failed: {msg}")

        start = time.time()
        result = await skill.execute(params)
        result.duration_ms = (time.time() - start) * 1000

        for hook in self._hooks["after_execute"]:
            await hook(skill_id, params, result)

        return result

    def add_hook(self, event: str, handler: HookHandler) -> None:
        """添加钩子（必须是 async callable）."""
        if event in self._hooks:
            self._hooks[event].append(handler)

    async def start_all(self) -> None:
        """启动所有技能."""
        for skill in self._skills.values():
            await skill.start()

    async def stop_all(self) -> None:
        """停止所有技能."""
        for skill in self._skills.values():
            await skill.stop()

    def get_stats(self) -> dict[str, Any]:
        """获取统计."""
        return {
            "total_skills": len(self._skills),
            "by_category": {c.value: len(ids) for c, ids in self._categories.items()},
            "active": sum(1 for s in self._skills.values() if s.get_status() == SkillStatus.ACTIVE),
        }
