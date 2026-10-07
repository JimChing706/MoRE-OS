"""零依赖 JSON Schema 子集校验器（技能参数 ``config_schema`` 用）。

环境无 ``jsonschema`` / ``fastjsonschema`` 且网络受限，故实现一个**明确定义的
子集**校验器，覆盖技能参数真正需要的约束：

    type / required / properties / additionalProperties / enum / const
    minimum / maximum / exclusiveMinimum / exclusiveMaximum
    minLength / maxLength / pattern / minItems / maxItems / items
    format(uri | email | date-time)

**安全策略**：不认识的复杂关键字（``anyOf`` / ``oneOf`` / ``$ref`` …）一律**忽略**
而不误拦——宁可漏检特殊组合，也不让合法入参被错误拒绝。跨字段条件规则仍由各技能
的 ``validate()`` 负责。

错误提示统一为 ``<path>: <原因>``，如::

    params.limit: 99 超过最大值 50
    params.provider: 取值 'bing' 不在允许集合 ['duckduckgo', 'serpapi'] 内
    params.code: 缺少必填字段
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

__all__ = ["SchemaError", "check_params", "is_valid", "validate_params"]

_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SchemaError(ValueError):
    """参数不符合 ``config_schema``。"""


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "null":
        return value is None
    return True  # 未知类型名 → 不拦截


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return type(value).__name__


def _check_format(value: str, fmt: str) -> str | None:
    if fmt == "uri":
        from urllib.parse import urlparse

        parsed = urlparse(value)
        if not parsed.scheme:
            return "不是合法 URI（缺少 scheme）"
        if parsed.scheme in ("http", "https") and not parsed.netloc:
            return "不是合法 URI（缺少主机名）"
        return None
    if fmt == "email":
        return None if _EMAIL_RE.match(value) else "不是合法邮箱地址"
    if fmt == "date-time":
        from datetime import datetime

        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return None
        except ValueError:
            return "不是合法 ISO-8601 日期时间"
    return None


def _validate(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        return

    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, t) for t in types):
            errors.append(
                f"{path}: 期望类型 {'/'.join(str(t) for t in types)}，实际 {_type_name(value)}"
            )
            return  # 类型不符时不再深挖子约束

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 必须等于 {schema['const']!r}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 取值 {value!r} 不在允许集合 {schema['enum']!r} 内")

    if isinstance(value, str):
        min_len, max_len = schema.get("minLength"), schema.get("maxLength")
        if min_len is not None and len(value) < min_len:
            errors.append(f"{path}: 长度 {len(value)} 小于最小长度 {min_len}")
        if max_len is not None and len(value) > max_len:
            errors.append(f"{path}: 长度 {len(value)} 超过最大长度 {max_len}")
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, value):
            errors.append(f"{path}: 不匹配模式 {pattern!r}")
        fmt = schema.get("format")
        if fmt:
            problem = _check_format(value, fmt)
            if problem:
                errors.append(f"{path}: {problem}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        bound_ops: tuple[tuple[str, Callable[[Any, Any], bool], str], ...] = (
            ("minimum", lambda a, b: a < b, "小于最小值"),
            ("maximum", lambda a, b: a > b, "超过最大值"),
            ("exclusiveMinimum", lambda a, b: a <= b, "不大于（应 >）"),
            ("exclusiveMaximum", lambda a, b: a >= b, "不小于（应 <）"),
        )
        for key, op, label in bound_ops:
            bound = schema.get(key)
            if bound is not None and op(value, bound):
                errors.append(f"{path}: {value} {label} {bound}")

    if isinstance(value, dict):
        for field in schema.get("required", []) or []:
            if field not in value:
                errors.append(f"{path}.{field}: 缺少必填字段")
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in value:
                _validate(value[key], sub, f"{path}.{key}", errors)
        extra = schema.get("additionalProperties", True)
        if extra is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}.{key}: 不认识的字段（additionalProperties=false）")
        elif isinstance(extra, dict):
            for key in value:
                if key not in props:
                    _validate(value[key], extra, f"{path}.{key}", errors)

    if isinstance(value, list):
        min_items, max_items = schema.get("minItems"), schema.get("maxItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: 元素数 {len(value)} 少于 {min_items}")
        if max_items is not None and len(value) > max_items:
            errors.append(f"{path}: 元素数 {len(value)} 超过 {max_items}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{i}]", errors)


def validate_params(params: Any, schema: dict[str, Any] | None, path: str = "params") -> list[str]:
    """按 JSON Schema 校验 ``params``，返回违规描述列表（空 = 通过）。"""
    if not schema:
        return []
    errors: list[str] = []
    _validate(params, schema, path, errors)
    return errors


def is_valid(params: Any, schema: dict[str, Any] | None) -> bool:
    return not validate_params(params, schema)


def check_params(
    params: Any, schema: dict[str, Any] | None, *, skill_id: str = ""
) -> tuple[bool, str]:
    """返回 ``(ok, message)``；``message`` 为标准化错误提示（ok 时为空串）。"""
    errors = validate_params(params, schema)
    if not errors:
        return True, ""
    prefix = f"skill {skill_id!r} " if skill_id else ""
    return False, f"{prefix}参数校验失败: " + "; ".join(errors)
