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
    """R-3：query 现返回结构化结果 {query,matched,returned,results}。"""
    r = await DataAnalysisSkill().execute(
        {"data": "[1,2,3]", "operation": "query", "query": "2", "format": "auto"}
    )
    assert r.success is True
    assert r.output == {"query": "2", "matched": 1, "returned": 1, "results": [2]}


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


# ---------------------------------------------------------------------------
# R-2：搜索源不得静默降级
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serpapi_without_key_fails_explicitly(monkeypatch):
    """回归：此前 serpapi 缺 key 会静默改走 DuckDuckGo 且 metadata 仍报 serpapi。"""
    from more_core.skills import WebSearchSkill

    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    r = await WebSearchSkill().execute({"query": "x", "provider": "serpapi", "limit": 3})

    assert r.success is False
    assert "SERPAPI_API_KEY" in (r.error or "")
    assert "不再静默降级" in (r.error or "")


@pytest.mark.asyncio
async def test_serpapi_uses_env_key(monkeypatch):
    from more_core.skills import WebSearchSkill

    called: dict[str, object] = {}

    async def fake_serpapi(self, query, limit):
        called["query"], called["limit"] = query, limit
        return [{"title": "t", "url": "u", "snippet": "s"}]

    monkeypatch.setattr(WebSearchSkill, "_search_serpapi", fake_serpapi)
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    r = await WebSearchSkill().execute({"query": "abc", "provider": "serpapi", "limit": 2})
    assert r.success is True
    assert called == {"query": "abc", "limit": 2}
    assert r.metadata["provider_used"] == "serpapi"


@pytest.mark.asyncio
async def test_serpapi_uses_config_key(monkeypatch):
    from more_core.skills import WebSearchSkill

    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    seen: dict[str, object] = {}

    async def fake_serpapi(self, query, limit):
        seen["called"] = True
        return []

    monkeypatch.setattr(WebSearchSkill, "_search_serpapi", fake_serpapi)
    r = await WebSearchSkill({"serpapi_key": "cfg-key"}).execute(
        {"query": "q", "provider": "serpapi"}
    )
    assert r.success is True and seen.get("called") is True


@pytest.mark.asyncio
async def test_unknown_provider_raises_not_fallback(monkeypatch):
    from more_core.skills import WebSearchSkill

    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        await WebSearchSkill()._search("bing", "x", 5)


@pytest.mark.asyncio
async def test_duckduckgo_path_reports_provider_used(monkeypatch):
    from more_core.skills import WebSearchSkill

    async def fake_ddg(self, query, limit):
        return []

    monkeypatch.setattr(WebSearchSkill, "_search_duckduckgo", fake_ddg)
    r = await WebSearchSkill().execute({"query": "x", "provider": "duckduckgo"})
    assert r.success is True
    assert r.metadata["provider_used"] == "duckduckgo"


# ---------------------------------------------------------------------------
# R-3：query 的明确定义语义
# ---------------------------------------------------------------------------

_ROWS = '[{"name":"a","age":30},{"name":"b","age":20},{"name":"c","age":40}]'


async def _q(query: str):
    return await DataAnalysisSkill().execute(
        {"data": _ROWS, "operation": "query", "query": query, "format": "json"}
    )


@pytest.mark.asyncio
async def test_query_numeric_comparisons():
    assert (await _q("age>25")).output["matched"] == 2
    assert (await _q("age>=30")).output["matched"] == 2
    assert (await _q("age<30")).output["matched"] == 1
    assert (await _q("age<=20")).output["matched"] == 1


@pytest.mark.asyncio
async def test_query_equality_not_equal_and_contains():
    assert (await _q("name=a")).output["results"] == [{"name": "a", "age": 30}]
    assert (await _q("name!=a")).output["matched"] == 2
    assert (await _q("name~b")).output["matched"] == 1


@pytest.mark.asyncio
async def test_query_no_match_returns_empty_not_whole_dataset():
    """回归：此前 dict/scalar 输入会静默忽略 query 并原样返回全部数据。"""
    r = await _q("zzz")
    assert r.success is True
    assert r.output["matched"] == 0
    assert r.output["results"] == []


@pytest.mark.asyncio
async def test_query_without_field_does_substring_match():
    r = await _q("b")
    assert r.success is True
    assert r.output["matched"] == 1  # {"name":"b","age":20}


@pytest.mark.asyncio
async def test_query_malformed_numeric_raises_structured_error():
    r = await _q("age>abc")
    assert r.success is False
    assert "需要数值" in (r.error or "")


@pytest.mark.asyncio
async def test_query_empty_returns_all_with_zero_cap_semantics():
    r = await _q("")
    assert r.success is True
    assert r.output["matched"] == 3
    assert r.output["returned"] == 3


@pytest.mark.asyncio
async def test_query_caps_results_at_ten():
    data = "[" + ",".join(str(i) for i in range(25)) + "]"
    r = await DataAnalysisSkill().execute(
        {"data": data, "operation": "query", "query": "1", "format": "json"}
    )
    assert r.success is True
    assert r.output["matched"] > 10
    assert r.output["returned"] == 10
    assert len(r.output["results"]) == 10
