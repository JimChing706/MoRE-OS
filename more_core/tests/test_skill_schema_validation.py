"""技能参数 config_schema 校验测试。

覆盖：零依赖 JSON Schema 子集校验器的各关键字、5 个内置技能的完整入参契约
（类型/必填/范围/枚举/格式）、以及 SkillManager.execute 的统一拦截与标准化错误。
"""

from __future__ import annotations

import pytest

from more_core.governance import observability as obs
from more_core.skills import create_default_skill_manager
from more_core.skills.base import (
    Skill,
    SkillCategory,
    SkillManager,
    SkillMetadata,
    SkillResult,
)
from more_core.skills.schema import check_params, validate_params

# ---------------------------------------------------------------------------
# 1. 校验器单元测试（各关键字）
# ---------------------------------------------------------------------------

_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 8},
        "n": {"type": "integer", "minimum": 1, "maximum": 10},
        "ratio": {"type": "number", "exclusiveMinimum": 0},
        "mode": {"type": "string", "enum": ["a", "b"]},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        "url": {"type": "string", "format": "uri"},
        "pat": {"type": "string", "pattern": "^[a-z]+$"},
    },
    "required": ["name"],
    "additionalProperties": False,
}


def test_valid_object_passes():
    assert (
        validate_params(
            {
                "name": "ok",
                "n": 5,
                "ratio": 0.5,
                "mode": "a",
                "tags": ["x"],
                "url": "https://e.com",
                "pat": "abc",
            },
            _SCHEMA,
        )
        == []
    )


@pytest.mark.parametrize(
    "params,needle",
    [
        ({}, "缺少必填字段"),
        ({"name": "ok", "n": "x"}, "期望类型 integer"),
        ({"name": "ok", "n": 99}, "超过最大值 10"),
        ({"name": "ok", "n": 0}, "小于最小值 1"),
        ({"name": "ok", "ratio": 0}, "不大于（应 >）"),
        ({"name": ""}, "小于最小长度 1"),
        ({"name": "toolongvalue"}, "超过最大长度 8"),
        ({"name": "ok", "mode": "z"}, "不在允许集合"),
        ({"name": "ok", "tags": ["a", "b", "c"]}, "超过 2"),
        ({"name": "ok", "tags": [1]}, "期望类型 string"),
        ({"name": "ok", "url": "notaurl"}, "不是合法 URI"),
        ({"name": "ok", "pat": "ABC"}, "不匹配模式"),
        ({"name": "ok", "extra": 1}, "不认识的字段"),
        ({"name": "ok", "n": True}, "期望类型 integer"),  # bool 不算 integer
    ],
)
def test_invalid_cases_are_rejected(params, needle):
    errors = validate_params(params, _SCHEMA)
    assert errors, f"应被拦截: {params}"
    assert any(needle in e for e in errors), errors


def test_non_object_params_rejected():
    assert validate_params("nope", _SCHEMA)


def test_empty_schema_is_permissive():
    assert validate_params({"anything": 1}, None) == []
    assert validate_params({"anything": 1}, {}) == []


def test_unknown_keywords_are_ignored_not_failing():
    # 不认识的复杂关键字不应误拦合法入参
    schema = {
        "type": "object",
        "anyOf": [{"required": ["x"]}],
        "properties": {"x": {"type": "string"}},
    }
    assert validate_params({"x": "ok"}, schema) == []


def test_check_params_returns_standard_message():
    ok, msg = check_params({"n": 5}, _SCHEMA, skill_id="demo")
    assert ok is False
    assert "skill 'demo'" in msg
    assert "参数校验失败" in msg
    assert "params.name" in msg


# ---------------------------------------------------------------------------
# 2. 5 个内置技能的入参契约
# ---------------------------------------------------------------------------


def _schemas() -> dict[str, dict]:
    mgr = create_default_skill_manager()
    return {m.id: m.config_schema for m in mgr.list_skills()}


def test_all_builtin_skills_have_proper_json_schema():
    schemas = _schemas()
    assert set(schemas) == {"web.search", "web.browse", "code.execute", "data.analyze", "api.call"}
    for sid, schema in schemas.items():
        assert schema, f"{sid} 缺少 config_schema"
        assert schema.get("type") == "object", sid
        assert schema.get("properties"), sid
        assert isinstance(schema.get("required"), list), sid
        assert schema.get("additionalProperties") is False, sid


@pytest.mark.parametrize(
    "sid,good,bad,needle",
    [
        ("web.search", {"query": "hello"}, {"query": ""}, "小于最小长度"),
        ("web.search", {"query": "hi", "limit": 5}, {"query": "hi", "limit": 999}, "超过最大值 50"),
        (
            "web.search",
            {"query": "hi", "provider": "serpapi"},
            {"query": "hi", "provider": "bing"},
            "不在允许集合",
        ),
        ("web.browse", {"url": "https://example.com"}, {"url": "ftp://x"}, "不匹配模式"),
        ("web.browse", {"url": "https://example.com"}, {"url": "not-a-url"}, "不是合法 URI"),
        (
            "web.browse",
            {"url": "https://e.com", "extract": "json"},
            {"url": "https://e.com", "extract": "xml"},
            "不在允许集合",
        ),
        ("code.execute", {"code": "print(1)"}, {}, "缺少必填字段"),
        (
            "code.execute",
            {"code": "x", "language": "python"},
            {"code": "x", "language": "ruby"},
            "不在允许集合",
        ),
        (
            "code.execute",
            {"code": "x", "timeout": 30},
            {"code": "x", "timeout": 9999},
            "超过最大值 300",
        ),
        ("data.analyze", {"data": "a,b\n1,2"}, {"operation": "parse"}, "缺少必填字段"),
        (
            "data.analyze",
            {"data": "x", "operation": "stats"},
            {"data": "x", "operation": "nope"},
            "不在允许集合",
        ),
        (
            "data.analyze",
            {"data": "x", "format": "csv"},
            {"data": "x", "format": "xml"},
            "不在允许集合",
        ),
        ("api.call", {"url": "https://api.example.com"}, {"url": "notaurl"}, "不是合法 URI"),
        (
            "api.call",
            {"url": "https://api.example.com", "method": "POST"},
            {"url": "https://a.com", "method": "TRACE"},
            "不在允许集合",
        ),
        (
            "api.call",
            {"url": "https://api.example.com", "timeout": 10},
            {"url": "https://a.com", "timeout": 0},
            "小于最小值 1",
        ),
    ],
)
def test_builtin_skill_param_contracts(sid, good, bad, needle):
    schema = _schemas()[sid]
    assert validate_params(good, schema) == [], f"{sid} 合法入参被误拦: {good}"
    errors = validate_params(bad, schema)
    assert errors, f"{sid} 非法入参未拦截: {bad}"
    assert any(needle in e for e in errors), (sid, errors)


# ---------------------------------------------------------------------------
# 3. SkillManager.execute 集成：统一拦截 + 结构化失败 + 遥测
# ---------------------------------------------------------------------------


class _SchemaSkill(Skill):
    def __init__(self) -> None:
        super().__init__()
        self._md = SkillMetadata(
            id="t.demo",
            name="demo",
            description="",
            category=SkillCategory.TOOLS,
            config_schema={
                "type": "object",
                "properties": {"n": {"type": "integer", "minimum": 1}},
                "required": ["n"],
                "additionalProperties": False,
            },
        )
        self.executed = 0

    @property
    def metadata(self) -> SkillMetadata:
        return self._md

    async def validate(self, params: dict) -> tuple[bool, str]:
        return True, ""

    async def execute(self, params: dict) -> SkillResult:
        self.executed += 1
        return SkillResult(success=True, output=params["n"])


@pytest.mark.asyncio
async def test_execute_blocks_invalid_params_before_running():
    mgr = SkillManager()
    skill = _SchemaSkill()
    mgr.register(skill)

    result = await mgr.execute("t.demo", {"n": "not-int"})

    assert result.success is False
    assert "Validation failed" in (result.error or "")
    assert "params.n" in (result.error or "")
    assert skill.executed == 0, "非法入参不得进入技能体"
    assert skill.metadata.usage_count == 1


@pytest.mark.asyncio
async def test_execute_allows_valid_params():
    mgr = SkillManager()
    skill = _SchemaSkill()
    mgr.register(skill)

    result = await mgr.execute("t.demo", {"n": 3})

    assert result.success is True
    assert result.output == 3
    assert skill.executed == 1


@pytest.mark.asyncio
async def test_schema_rejection_is_telemetered():
    mgr = SkillManager()
    mgr.register(_SchemaSkill())
    await mgr.execute("t.demo", {})

    st = obs.query_skill_stats(3600)
    assert st["runs"] == 1
    assert st["success_rate"] == 0.0
