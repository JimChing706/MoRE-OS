"""ZEN_RULES Enforcement - 规则执行与合规检查."""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable
from functools import wraps

_log = logging.getLogger(__name__)


class RuleSeverity(Enum):
    """规则严重级别"""
    P0_FATAL = "p0_fatal"     # 绝对禁止
    P1_CRITICAL = "p1_critical"  # 严重
    P2_MAJOR = "p2_major"     # 重要
    P3_MINOR = "p3_minor"     # 一般


class RuleCategory(Enum):
    """规则类别"""
    SAFETY = "safety"         # 安全
    SIMPLICITY = "simplicity" # 简洁
    CONTROL = "control"       # 可控
    TRACEABLE = "traceable"  # 可追溯
    EVOLUTION = "evolution"   # 进化
    LLM_SPECIFIC = "llm"      # LLM特定
    PROHIBITION = "prohibition"  # 禁止


@dataclass
class ZENRule:
    """ZEN规则定义"""
    id: str
    name: str
    category: RuleCategory
    severity: RuleSeverity
    description: str
    check_fn: Callable[..., Any] | None = None


@dataclass
class ViolationRecord:
    """违规记录"""
    rule_id: str
    rule_name: str
    severity: RuleSeverity
    category: RuleCategory
    timestamp: float
    context: dict[str, Any]
    resolved: bool = False
    resolution: str = ""


class ZENRulesEnforcer:
    """ZEN规则执行器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._rules: dict[str, ZENRule] = {}
        self._violations: list[ViolationRecord] = []
        self._max_violations = 1000
        self._callbacks: dict[RuleSeverity, list[Callable[..., Any]]] = {
            RuleSeverity.P0_FATAL: [],
            RuleSeverity.P1_CRITICAL: [],
            RuleSeverity.P2_MAJOR: [],
            RuleSeverity.P3_MINOR: [],
        }
        self._register_default_rules()
    
    def _register_default_rules(self):
        """注册默认规则"""
        default_rules = [
            # 安全规则
            ZENRule("ZEN-01", "零信任原则", RuleCategory.SAFETY, RuleSeverity.P1_CRITICAL,
                   "永不信任,始终验证"),
            ZENRule("ZEN-02", "最小权限", RuleCategory.SAFETY, RuleSeverity.P1_CRITICAL,
                   "权限如指尖沙"),
            ZENRule("ZEN-03", "纵深防御", RuleCategory.SAFETY, RuleSeverity.P1_CRITICAL,
                   "防御如洋葱"),
            
            # 简洁规则
            ZENRule("ZEN-04", "代码简洁", RuleCategory.SIMPLICITY, RuleSeverity.P3_MINOR,
                   "代码如诗"),
            ZENRule("ZEN-05", "接口简洁", RuleCategory.SIMPLICITY, RuleSeverity.P3_MINOR,
                   "接口如门"),
            
            # 可控规则
            ZENRule("ZEN-07", "决策可控", RuleCategory.CONTROL, RuleSeverity.P2_MAJOR,
                   "决策如钟"),
            ZENRule("ZEN-08", "状态可控", RuleCategory.CONTROL, RuleSeverity.P2_MAJOR,
                   "状态如镜"),
            ZENRule("ZEN-09", "演进可控", RuleCategory.CONTROL, RuleSeverity.P2_MAJOR,
                   "演进如山"),
            
            # 可追溯规则
            ZENRule("ZEN-10", "操作追溯", RuleCategory.TRACEABLE, RuleSeverity.P2_MAJOR,
                   "操作如影"),
            ZENRule("ZEN-11", "决策追溯", RuleCategory.TRACEABLE, RuleSeverity.P2_MAJOR,
                   "决策如链"),
            ZENRule("ZEN-12", "异常追溯", RuleCategory.TRACEABLE, RuleSeverity.P2_MAJOR,
                   "异常如痕"),
            
            # LLM特定规则
            ZENRule("ZEN-16", "LLM调用", RuleCategory.LLM_SPECIFIC, RuleSeverity.P2_MAJOR,
                   "LLM如剑"),
            ZENRule("ZEN-17", "LLM输出", RuleCategory.LLM_SPECIFIC, RuleSeverity.P1_CRITICAL,
                   "输出如镜"),
            ZENRule("ZEN-18", "成本控制", RuleCategory.LLM_SPECIFIC, RuleSeverity.P2_MAJOR,
                   "成本如尺"),
            
            # 禁止规则
            ZENRule("ZEN-19", "绝对禁止", RuleCategory.PROHIBITION, RuleSeverity.P0_FATAL,
                   "禁如红线"),
        ]
        
        for rule in default_rules:
            self._rules[rule.id] = rule
    
    def register_callback(self, severity: RuleSeverity, callback: Callable[..., Any]) -> None:
        self._callbacks[severity].append(callback)
    
    def check_violation(self, rule_id: str, context: dict[str, Any]) -> bool:
        """检查是否违规"""
        if rule_id not in self._rules:
            return False
        
        rule = self._rules[rule_id]
        
        # 如果有自定义检查函数
        if rule.check_fn:
            try:
                if not rule.check_fn(context):
                    self._record_violation(rule, context)
                    return True
            except Exception:
                _log.exception("check_fn for rule %s raised", rule_id)
        
        return False
    
    def _record_violation(self, rule: ZENRule, context: dict[str, Any]) -> None:
        """记录违规"""
        violation = ViolationRecord(
            rule_id=rule.id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            timestamp=time.time(),
            context=context,
        )
        
        self._violations.append(violation)
        if len(self._violations) > self._max_violations:
            self._violations.pop(0)
        
        # 触发回调
        for callback in self._callbacks.get(rule.severity, []):
            try:
                callback(violation)
            except Exception:
                _log.exception("violation callback failed for rule %s", violation.rule_id)
    
    def get_violations(self, severity: RuleSeverity | None = None) -> list[ViolationRecord]:
        """获取违规记录"""
        if severity is None:
            return list(self._violations)
        return [v for v in self._violations if v.severity == severity]
    
    def get_compliance_report(self) -> dict[str, Any]:
        """获取合规报告"""
        total = len(self._violations)
        by_severity = {s.value: 0 for s in RuleSeverity}
        by_category = {c.value: 0 for c in RuleCategory}
        
        for v in self._violations:
            by_severity[v.severity.value] += 1
            by_category[v.category.value] += 1
        
        return {
            "total_violations": total,
            "by_severity": by_severity,
            "by_category": by_category,
            "active_rules": len(self._rules),
            "p0_fatal_count": by_severity[RuleSeverity.P0_FATAL.value],
            "compliant": by_severity[RuleSeverity.P0_FATAL.value] == 0,
        }
    
    def resolve_violation(self, violation_id: int, resolution: str) -> bool:
        """解决违规"""
        if 0 <= violation_id < len(self._violations):
            self._violations[violation_id].resolved = True
            self._violations[violation_id].resolution = resolution
            return True
        return False
    
    def list_rules(self) -> list[dict[str, Any]]:
        """列出所有规则"""
        return [
            {
                "id": r.id,
                "name": r.name,
                "category": r.category.value,
                "severity": r.severity.value,
                "description": r.description,
            }
            for r in self._rules.values()
        ]


# 全局单例
_enforcer = ZENRulesEnforcer()


def get_enforcer() -> ZENRulesEnforcer:
    return _enforcer


def enforce(rule_id: str):
    """装饰器: 强制规则检查"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            enforcer = get_enforcer()
            context = {
                "function": func.__name__,
                "args": str(args)[:100],
                "kwargs": str(kwargs)[:100],
            }
            if enforcer.check_violation(rule_id, context):
                raise PermissionError(f"ZEN规则违反: {rule_id}")
            return func(*args, **kwargs)
        return wrapper
    return decorator