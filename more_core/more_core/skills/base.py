"""Skill Package System - 前沿技术技能实现.

参考: Hermes Skills, OpenFang Hands
设计理念: 模块化、可扩展、自包含
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .schema import check_params

# Type alias for hook handlers — must be awaitable since execute() awaits them.
HookHandler = Callable[..., Awaitable[Any]]

_log = logging.getLogger(__name__)

# 单次技能执行超时（秒）。0/空 = 不启用。可用 MORE_SKILL_TIMEOUT_S 覆盖。
_DEFAULT_SKILL_TIMEOUT_S = float(os.getenv("MORE_SKILL_TIMEOUT_S") or 120)


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
    # 交付台账字段：维护责任人与部署要求（供 SkillDeliveryLedger 归档）
    maintainer: str = "MoRE OS Core Team"
    deployment: dict[str, Any] = field(default_factory=dict)
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

    @abstractmethod
    async def execute(self, params: dict[str, Any]) -> SkillResult:
        """执行技能."""

    @abstractmethod
    async def validate(self, params: dict[str, Any]) -> tuple[bool, str]:
        """验证参数."""

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

    def __init__(self, timeout_s: float | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self._categories: dict[SkillCategory, list[str]] = {c: [] for c in SkillCategory}
        self._hooks: dict[str, list[HookHandler]] = {
            "before_execute": [],
            "after_execute": [],
            "on_error": [],
        }
        # 0 表示禁用超时保护（默认 120s，可用 MORE_SKILL_TIMEOUT_S 覆盖）
        self._timeout_s = _DEFAULT_SKILL_TIMEOUT_S if timeout_s is None else float(timeout_s)

    def register(self, skill: Skill) -> None:
        """注册技能（重复 id 覆盖旧实现，避免分类里出现重复条目）。"""
        sid = skill.metadata.id
        existing = self._skills.get(sid)
        if existing is not None:
            old_cat = existing.metadata.category
            if sid in self._categories[old_cat]:
                self._categories[old_cat].remove(sid)
            _log.warning("skill %s re-registered; previous instance replaced", sid)
        self._skills[sid] = skill
        self._categories[skill.metadata.category].append(sid)

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
        """执行技能。

        增强点（对应"产出正确性 / 可观测性"）：
        * **错误隔离**：技能内部异常统一转成 ``SkillResult(success=False)``，
          不让异常击穿调用方；失败会触发 ``on_error`` 钩子。
        * **超时保护**：单次执行超过 ``timeout_s`` 返回结构化失败（0 = 关闭）。
        * **指标统计**：更新 ``usage_count`` / ``success_rate`` / ``avg_duration_ms``
          （此前这些字段恒为初值，看板全是假数据）。
        * **遥测落库**：写入 observability 的 ``skill_runs`` 表（若可用）。
        """
        skill = self._skills.get(skill_id)
        if not skill:
            return SkillResult(success=False, error=f"Skill not found: {skill_id}")

        for hook in self._hooks["before_execute"]:
            await hook(skill_id, params)

        # 1) config_schema 结构化校验（JSON Schema 子集）：类型/必填/范围/枚举/格式
        ok_schema, schema_msg = check_params(
            params, skill.metadata.config_schema, skill_id=skill_id
        )
        if not ok_schema:
            return await self._finalize(
                skill_id,
                skill,
                params,
                success=False,
                error=f"Validation failed: {schema_msg}",
                duration_ms=0.0,
            )

        # 2) 技能自身语义校验（跨字段条件等，异常同样隔离）
        try:
            valid, msg = await skill.validate(params)
        except Exception as exc:  # noqa: BLE001
            return await self._finalize(
                skill_id,
                skill,
                params,
                success=False,
                error=f"validation error: {type(exc).__name__}: {exc}",
                duration_ms=0.0,
            )
        if not valid:
            return await self._finalize(
                skill_id,
                skill,
                params,
                success=False,
                error=f"Validation failed: {msg}",
                duration_ms=0.0,
            )

        start = time.perf_counter()
        try:
            coro = skill.execute(params)
            if self._timeout_s and self._timeout_s > 0:
                result = await asyncio.wait_for(coro, timeout=self._timeout_s)
            else:
                result = await coro
        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start) * 1000
            return await self._finalize(
                skill_id,
                skill,
                params,
                success=False,
                error=f"skill timed out after {self._timeout_s}s",
                duration_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001 - 技能异常必须隔离
            duration_ms = (time.perf_counter() - start) * 1000
            text = str(exc).strip() or type(exc).__name__
            return await self._finalize(
                skill_id,
                skill,
                params,
                success=False,
                error=f"{type(exc).__name__}: {text}",
                duration_ms=duration_ms,
            )

        duration_ms = (time.perf_counter() - start) * 1000
        if not isinstance(result, SkillResult):
            return await self._finalize(
                skill_id,
                skill,
                params,
                success=False,
                error=f"skill returned {type(result).__name__}, expected SkillResult",
                duration_ms=duration_ms,
            )
        result.duration_ms = duration_ms
        return await self._finalize(
            skill_id,
            skill,
            params,
            success=result.success,
            error=result.error,
            duration_ms=duration_ms,
            result=result,
        )

    async def _finalize(
        self,
        skill_id: str,
        skill: Skill,
        params: dict[str, Any],
        *,
        success: bool,
        error: str | None,
        duration_ms: float,
        result: SkillResult | None = None,
    ) -> SkillResult:
        """统一收尾：更新指标 → 失败钩子 → 落库遥测 → after 钩子。"""
        out = (
            result
            if result is not None
            else SkillResult(success=success, error=error, duration_ms=duration_ms)
        )
        self._update_metrics(skill, success, duration_ms)

        if not success:
            for hook in self._hooks["on_error"]:
                try:
                    await hook(skill_id, params, out)
                except Exception:  # pragma: no cover - 钩子失败不得影响结果  # noqa: BLE001
                    _log.warning("skill on_error hook failed for %s", skill_id, exc_info=True)

        self._record_telemetry(skill_id, skill, success, duration_ms, error)

        for hook in self._hooks["after_execute"]:
            await hook(skill_id, params, out)

        return out

    @staticmethod
    def _update_metrics(skill: Skill, success: bool, duration_ms: float) -> None:
        """累计更新 usage_count / success_rate / avg_duration_ms（真值，非初值）。"""
        md = skill.metadata
        prev = md.usage_count
        md.usage_count = prev + 1
        ok = 1.0 if success else 0.0
        md.success_rate = ok if prev == 0 else (md.success_rate * prev + ok) / md.usage_count
        md.avg_duration_ms = (
            duration_ms if prev == 0 else (md.avg_duration_ms * prev + duration_ms) / md.usage_count
        )

    @staticmethod
    def _record_telemetry(
        skill_id: str, skill: Skill, success: bool, duration_ms: float, error: str | None
    ) -> None:
        """写入 observability.skill_runs（不可用时静默跳过）。"""
        try:
            from ..governance import observability as _obs

            _obs.record_skill_run(
                skill_id=skill_id,
                category=skill.metadata.category.value,
                success=success,
                duration_ms=duration_ms,
                error=(error or "")[:400],
            )
        except Exception:  # pragma: no cover - 遥测不得影响执行  # noqa: BLE001, S110
            pass

    def add_hook(self, event: str, handler: HookHandler) -> None:
        """添加钩子（必须是 async callable）."""
        if event in self._hooks:
            self._hooks[event].append(handler)

    async def start_all(self) -> None:
        """启动所有技能（单个失败不影响其它技能）。"""
        for sid, skill in self._skills.items():
            try:
                await skill.start()
            except Exception:  # pragma: no cover - 单个技能启动失败不得阻断全体  # noqa: BLE001
                _log.warning("skill %s failed to start", sid, exc_info=True)

    async def stop_all(self) -> None:
        """停止所有技能（单个失败不影响其它技能）。"""
        for sid, skill in self._skills.items():
            try:
                await skill.stop()
            except Exception:  # pragma: no cover  # noqa: BLE001
                _log.warning("skill %s failed to stop", sid, exc_info=True)

    def get_stats(self) -> dict[str, Any]:
        """获取统计（含真实执行量与成功率，而非仅注册数）。"""
        metas = [s.metadata for s in self._skills.values()]
        total_runs = sum(m.usage_count for m in metas)
        weighted_ok = sum(m.success_rate * m.usage_count for m in metas)
        return {
            "total_skills": len(self._skills),
            "by_category": {c.value: len(ids) for c, ids in self._categories.items()},
            "active": sum(1 for s in self._skills.values() if s.get_status() == SkillStatus.ACTIVE),
            "total_runs": total_runs,
            "success_rate": round(weighted_ok / total_runs, 3) if total_runs else 0.0,
            "timeout_s": self._timeout_s,
        }
