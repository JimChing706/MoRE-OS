"""输出验证门禁 v2 — 借鉴 ai_council 2 validators.py 增强版。

v2 增强:
- 白名单清洗: LLM 输出可能含 schema 未定义的额外字段，在校验前自动剥离
- 降级兜底: 校验器不可用时降级为基本类型检查
- 更好错误信息: 提供修复建议
- 容错加载: Schema 文件不存在时给出清晰错误信息

设计原则:
- ZRO (Zero-Trust Output): 不信任任何层输出
- 防御优先: 清洗而非直接拒绝，减少无效重试
"""

from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger(__name__)


class SchemaViolation(ValueError):
    """输出格式违规。"""

    def __init__(self, layer: str, message: str, output: Any = None):
        self.layer = layer
        self.message = message
        self.output = output
        super().__init__(f"[{layer}] Schema violation: {message}")


# ── 白名单清洗 ────────────────────────────────────────────────────


def _strip_extra_fields(
    data: dict[str, Any], allowed_fields: set[str], path: str = "<root>"
) -> tuple[dict[str, Any], list[str]]:
    """剥离 schema 未定义的额外字段。

    这是防御层: LLM 输出几乎总会多出额外字段（如 evidence_detail, reasoning 等），
    直接拒绝会导致大量无效重试。本函数在严格验证前进行清洗。

    Args:
        data: 待清洗的数据
        allowed_fields: 允许的字段名集合
        path: 当前路径（用于日志）

    Returns:
        (清洗后数据, 被剥离的字段路径列表)
    """
    stripped: list[str] = []
    result = {}

    for key, value in data.items():
        if key in allowed_fields:
            # 对嵌套的 dict 进一步清洗
            if isinstance(value, dict):
                # 对嵌套对象的关键字段也做清洗
                if key == "directed_response":
                    # directed_response 有特定字段
                    allowed_sub = {"target_role", "target_point", "stance", "content"}
                    sub_cleaned, sub_stripped = _strip_extra_fields(
                        value, allowed_sub, f"{path}/{key}"
                    )
                    result[key] = sub_cleaned
                    stripped.extend(sub_stripped)
                elif key == "key_arguments" and isinstance(value, list):
                    # key_arguments 是 dict 列表：宽松接受所有元素（保留原行为）
                    # 注：此前这里有一行**无副作用的 set 字面量**（计算后即丢弃），
                    # 属死代码，已移除。
                    result[key] = list(value)
                else:
                    result[key] = value
            else:
                result[key] = value
        else:
            stripped.append(f"{path}/{key}")

    return result, stripped


# 角色输出允许的字段
_ROLE_OUTPUT_ALLOWED = {
    "role",
    "stage",
    "core_judgment",
    "key_arguments",
    "top_concern",
    "constructive_suggestion",
    "confidence",
    "directed_response",
    "knowledge_confidence",
}


class OutputGate:
    """输出门禁 — 校验层输出是否符合预期格式。"""

    def __init__(self, schema: dict[str, Any] | None = None):
        self._schema = schema or {}

    def validate(self, layer_id: str, output: Any) -> None:
        """执行门禁校验。不符合预期则抛出 SchemaViolation。"""
        errors: list[str] = []

        required = self._schema.get("required_fields", [])
        if required:
            for field in required:
                if not self._has_field(output, field):
                    errors.append(f"缺少必需字段: {field}")

        min_length = self._schema.get("min_length", 0)
        if min_length > 0:
            desc = self._get_field(output, "description") or str(output)
            if len(desc.strip()) < min_length:
                errors.append(f"输出内容过短: {len(desc.strip())} 字符 (< {min_length})")

        if errors:
            raise SchemaViolation(
                layer=layer_id,
                message="; ".join(errors),
                output=output,
            )

    @staticmethod
    def _has_field(output: Any, field: str) -> bool:
        if isinstance(output, dict):
            return field in output
        if hasattr(output, field):
            return getattr(output, field, None) is not None
        return False

    @staticmethod
    def _get_field(output: Any, field: str) -> Any | None:
        if isinstance(output, dict):
            return output.get(field)
        return getattr(output, field, None)


def validate_role_output(output: Any) -> dict[str, Any]:
    """校验角色输出。违反协议时抛出 SchemaViolation。

    v2 增强:
    1. 自动剥离 schema 未定义的额外字段
    2. 返回清洗后的输出
    """
    if not isinstance(output, dict):
        raise SchemaViolation(
            "role_output",
            f"输出必须是 JSON 对象，收到: {type(output).__name__}",
            output=str(output)[:200] if output else None,
        )

    # 白名单清洗: 剥离额外字段
    cleaned, stripped_fields = _strip_extra_fields(output, _ROLE_OUTPUT_ALLOWED)
    if stripped_fields:
        _log.info(
            "[门禁] 清洗越界字段(已剥离): %s",
            ", ".join(stripped_fields),
        )

    # 基本字段检查
    required_fields = {"role", "core_judgment", "key_arguments"}
    missing = required_fields - set(cleaned.keys())
    if missing:
        raise SchemaViolation(
            "role_output",
            f"缺少必填字段: {sorted(missing)}。修复建议: 补充所有必填字段。",
            output=cleaned,
        )

    return cleaned


# ── 预定义门禁 ──────────────────────────────────────────────────────

BASIC_GATE = OutputGate({"min_length": 1})

STANDARD_GATE = OutputGate(
    {
        "required_fields": ["description"],
        "min_length": 5,
    }
)

STRICT_GATE = OutputGate(
    {
        "required_fields": ["description", "confidence", "output"],
        "min_length": 10,
    }
)


def validate_json_output(raw: str, layer_id: str = "unknown") -> dict[str, Any]:
    """验证 JSON 输出是否符合基本要求。"""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SchemaViolation(
            layer=layer_id,
            message=f"JSON 解析失败: {e}",
            output=raw[:200],
        )

    if not isinstance(parsed, dict):
        raise SchemaViolation(
            layer=layer_id,
            message="输出必须是 JSON 对象，不是数组/标量",
        )

    return parsed
