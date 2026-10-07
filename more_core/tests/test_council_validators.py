"""Council 输出门禁（validators.py）测试 —— 覆盖补齐。"""

from __future__ import annotations

import pytest

from more_core.council.validators import (
    BASIC_GATE,
    STANDARD_GATE,
    STRICT_GATE,
    OutputGate,
    SchemaViolation,
    _strip_extra_fields,
    validate_json_output,
    validate_role_output,
)

_GOOD_ROLE = {
    "role": "analyst",
    "core_judgment": "可行",
    "key_arguments": [{"point": "p", "reasoning": "r"}],
    "confidence": 0.8,
}


# ---------------------------------------------------------------------------
# _strip_extra_fields
# ---------------------------------------------------------------------------


def test_strip_extra_fields_keeps_allowed_and_reports_removed():
    cleaned, stripped = _strip_extra_fields({"keep": 1, "drop": 2}, {"keep"}, path="$")
    assert cleaned == {"keep": 1}
    assert stripped == ["$/drop"]


def test_strip_extra_fields_cleans_nested_directed_response():
    cleaned, stripped = _strip_extra_fields(
        {"directed_response": {"target_role": "x", "evil": 1}},
        {"directed_response"},
        path="$",
    )
    assert cleaned["directed_response"] == {"target_role": "x"}
    assert "$/directed_response/evil" in stripped


def test_strip_extra_fields_keeps_key_arguments_list():
    args = [{"point": "p", "extra": "ok"}]
    cleaned, _ = _strip_extra_fields({"key_arguments": args}, {"key_arguments"})
    assert cleaned["key_arguments"] == args


# ---------------------------------------------------------------------------
# SchemaViolation
# ---------------------------------------------------------------------------


def test_schema_violation_message_and_attrs():
    exc = SchemaViolation("L3", "bad output", output={"x": 1})
    assert exc.layer == "L3"
    assert exc.message == "bad output"
    assert exc.output == {"x": 1}
    assert "[L3] Schema violation: bad output" in str(exc)


# ---------------------------------------------------------------------------
# OutputGate
# ---------------------------------------------------------------------------


def test_gate_without_schema_passes_anything():
    OutputGate().validate("L0", "whatever")


def test_basic_gate_rejects_empty():
    with pytest.raises(SchemaViolation):
        BASIC_GATE.validate("L0", "")


def test_standard_gate_requires_description_and_min_length():
    STANDARD_GATE.validate("L0", {"description": "足够长的描述"})
    with pytest.raises(SchemaViolation) as ei:
        STANDARD_GATE.validate("L0", {"other": "x"})
    assert "缺少必需字段" in str(ei.value)

    with pytest.raises(SchemaViolation) as ei2:
        STANDARD_GATE.validate("L0", {"description": "短"})
    assert "过短" in str(ei2.value)


def test_strict_gate_requires_three_fields():
    long_desc = "这是一段足够长的描述内容用于满足严格门禁的最小长度要求"
    STRICT_GATE.validate("L0", {"description": long_desc, "confidence": 0.9, "output": "x"})
    with pytest.raises(SchemaViolation):
        STRICT_GATE.validate("L0", {"description": long_desc, "confidence": 0.9})


def test_gate_supports_object_attribute_access():
    class _Obj:
        description = "足够长的描述"

    STANDARD_GATE.validate("L0", _Obj())


# ---------------------------------------------------------------------------
# validate_role_output
# ---------------------------------------------------------------------------


def test_validate_role_output_ok():
    assert validate_role_output(_GOOD_ROLE) == _GOOD_ROLE


def test_validate_role_output_strips_extra_fields():
    out = dict(_GOOD_ROLE, evidence_detail="越界字段")
    cleaned = validate_role_output(out)
    assert "evidence_detail" not in cleaned
    assert cleaned["role"] == "analyst"


def test_validate_role_output_rejects_non_dict():
    with pytest.raises(SchemaViolation) as ei:
        validate_role_output(["not", "a", "dict"])
    assert "必须是 JSON 对象" in str(ei.value)


def test_validate_role_output_rejects_missing_fields_with_suggestion():
    with pytest.raises(SchemaViolation) as ei:
        validate_role_output({"role": "analyst"})
    msg = str(ei.value)
    assert "缺少必填字段" in msg and "修复建议" in msg


# ---------------------------------------------------------------------------
# validate_json_output
# ---------------------------------------------------------------------------


def test_validate_json_output_ok():
    assert validate_json_output('{"a": 1}', "L0") == {"a": 1}


def test_validate_json_output_invalid_json():
    with pytest.raises(SchemaViolation) as ei:
        validate_json_output("{not json", "L3")
    assert "JSON 解析失败" in str(ei.value)


def test_validate_json_output_rejects_non_object():
    with pytest.raises(SchemaViolation) as ei:
        validate_json_output("[1,2,3]", "L3")
    assert "必须是 JSON 对象" in str(ei.value)
