"""技能功能完整性回归（含 data.analyze 解析缺陷修复）。"""

from __future__ import annotations

import pytest

from more_core.skills import (
    CodeExecutionSkill,
    DataAnalysisSkill,
    create_default_skill_manager,
)


@pytest.mark.asyncio
async def test_data_analyze_parse():
    r = await DataAnalysisSkill().execute({"data": '{"a": 1}', "operation": "parse"})
    assert r.success is True
    assert r.output["parsed"] == {"a": 1}


@pytest.mark.asyncio
async def test_data_analyze_stats_computes_real_statistics():
    """回归：此前把原始字符串交给 _compute_stats，恒返回 {'type': 'str'}。"""
    r = await DataAnalysisSkill().execute(
        {"data": "[1,2,3,4]", "operation": "stats", "format": "auto"}
    )
    assert r.success is True
    assert r.output == {
        "count": 4, "numeric_count": 4, "sum": 10, "mean": 2.5, "min": 1, "max": 4,
    }


@pytest.mark.asyncio
async def test_data_analyze_transform_projects_keys():
    r = await DataAnalysisSkill().execute(
        {"data": '{"a": 1, "b": 2}', "operation": "transform",
         "transform": {"keys": ["a"]}, "format": "json"}
    )
    assert r.success is True
    assert r.output == {"a": 1}


@pytest.mark.asyncio
async def test_data_analyze_query_filters_list():
    r = await DataAnalysisSkill().execute(
        {"data": "[1,2,3]", "operation": "query", "query": "2", "format": "auto"}
    )
    assert r.success is True
    assert r.output == [2]


@pytest.mark.asyncio
async def test_code_execute_python_roundtrip():
    r = await CodeExecutionSkill().execute(
        {"code": "print(2 ** 10)", "language": "python", "timeout": 10}
    )
    assert r.success is True
    assert "1024" in str(r.output)


def test_declared_dependencies_match_implementation():
    """依赖声明必须与实际实现一致（此前误声明 pandas / beautifulsoup4）。"""
    metas = {m.id: m for m in create_default_skill_manager().list_skills()}
    assert "pandas" not in metas["data.analyze"].dependencies
    assert "beautifulsoup4" not in metas["web.browse"].dependencies
    assert metas["web.browse"].dependencies == ["httpx"]
