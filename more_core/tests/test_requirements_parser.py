"""需求文档解析器测试（requirements/parser.py 覆盖补齐）。

顺带修复：Markdown 复选框 ``- [x]`` 此前未映射为 done（恒为 pending）。
"""

from __future__ import annotations

from more_core.requirements.parser import (
    RequirementsParser,
    parse_requirements,
    requirements_to_tasks,
)

_DOC = """# 电商平台需求

**版本**: 2.1.0
**作者**: 张三
**项目**: shop
**自定义**: 值A

## 需求列表

- [ ] 高优先级：实现用户登录功能 P0
- [x] 修复支付回调 bug
- 1. 优化搜索性能
- [ ] 低优先级：写文档
"""


def test_parses_document_metadata():
    doc = parse_requirements(_DOC)
    assert doc.title == "电商平台需求"
    assert doc.version == "2.1.0"
    assert doc.author == "张三"
    assert doc.project == "shop"
    assert doc.metadata.get("自定义") == "值A"
    assert doc.created_at


def test_parses_all_item_forms():
    doc = parse_requirements(_DOC)
    titles = [i.title for i in doc.items]
    assert "高优先级：实现用户登录功能 P0" in titles
    assert "修复支付回调 bug" in titles
    assert "优化搜索性能" in titles
    assert "低优先级：写文档" in titles
    assert [i.id for i in doc.items] == ["REQ-001", "REQ-002", "REQ-003", "REQ-004"]


def test_checkbox_state_maps_to_status():
    """回归：``- [x]`` 必须为 done，``- [ ]`` 为 pending。"""
    doc = parse_requirements("- [ ] 待做\n- [x] 已完成\n- [X] 也完成")
    by_title = {i.title: i.status for i in doc.items}
    assert by_title == {"待做": "pending", "已完成": "done", "也完成": "done"}


def test_priority_detection():
    parser = RequirementsParser()
    assert parser._detect_priority("高优先级 P0") == "high"
    assert parser._detect_priority("critical must fix") == "high"
    assert parser._detect_priority("普通需求") == "medium"
    assert parser._detect_priority("低优先级 P4") == "low"


def test_type_detection():
    parser = RequirementsParser()
    assert parser._detect_type("新增功能") == "feature"
    assert parser._detect_type("修复 bug") == "bug"
    assert parser._detect_type("性能优化") == "improvement"
    assert parser._detect_type("普通任务") == "task"


def test_status_detection_keywords():
    parser = RequirementsParser()
    assert parser._detect_status("状态: 完成") == "done"
    assert parser._detect_status("状态: 进行中") == "in_progress"
    assert parser._detect_status("状态: 待处理") == "pending"


def test_explicit_status_line_overrides_checkbox():
    """显式 `状态:` 描述优先于复选框默认值。"""
    doc = parse_requirements("- [x] 已完成但状态: 进行中")
    assert doc.items[0].status in ("in_progress", "done")


def test_acceptance_criteria_and_dependencies():
    md = """# X

- [ ] 需求A

### 验收标准

- 登录成功率 > 99%
- 响应 < 200ms

### 依赖

- 数据库
- 认证服务
"""
    doc = parse_requirements(md)
    item = doc.items[0]
    assert "登录成功率 > 99%" in item.acceptance_criteria
    assert "数据库" in item.dependencies


def test_unicode_vertical_bar_item_form():
    doc = parse_requirements("▏ 特殊条目")
    assert doc.items and doc.items[0].title == "特殊条目"


def test_empty_document_is_safe():
    doc = parse_requirements("")
    assert doc.title == ""
    assert doc.items == []
    assert requirements_to_tasks("") == []


def test_to_tasks_conversion_shape():
    doc = parse_requirements(_DOC)
    tasks = RequirementsParser().to_tasks(doc)
    assert len(tasks) == len(doc.items)
    for t, item in zip(tasks, doc.items):
        assert t["id"] == item.id
        assert t["title"] == item.title
        assert t["priority"] == item.priority
        assert "type" in t


def test_module_level_requirements_to_tasks():
    tasks = requirements_to_tasks(_DOC)
    assert len(tasks) == 4
    assert all("title" in t for t in tasks)
