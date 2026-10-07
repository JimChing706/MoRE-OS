"""单测：Planner (planner.py)

目标：覆盖 Planner.plan() 的两条路径 (LLM / Fallback RULE_BASED_TETRIS_PLAN=7步)、
Step dataclass 字段、有效性校验等。共 ≥ 5 tests。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import copy

from more_core.core.native_executor.planner import (
    Planner,
    Step,
    RULE_BASED_TETRIS_PLAN,
)


def test_rule_based_plan_exactly_7_steps():
    """RULE_BASED_TETRIS_PLAN 必须恰好 7 步，且 id/title/action 合法。"""
    assert isinstance(RULE_BASED_TETRIS_PLAN, list)
    assert len(RULE_BASED_TETRIS_PLAN) == 7
    for s in RULE_BASED_TETRIS_PLAN:
        assert isinstance(s, Step)
        assert s.id, "每个 Step.id 不能为空"
        assert s.title, "每个 Step.title 不能为空"
        assert s.action in ("write_file", "cmd"), f"非法 action: {s.action}"


def test_rule_based_plan_dependencies():
    """RULE_BASED_TETRIS_PLAN 依赖图应形成可拓扑排序的 DAG。"""
    ids = {s.id for s in RULE_BASED_TETRIS_PLAN}
    for s in RULE_BASED_TETRIS_PLAN:
        for dep in s.depends_on:
            assert dep in ids, f"Step {s.id} 依赖不存在的 {dep}"
    # s6_cargo_build 必须依赖 s2 / s3；s7_cargo_test 依赖 s6
    by_id = {s.id: s for s in RULE_BASED_TETRIS_PLAN}
    assert "s2_lib_rs" in by_id["s6_cargo_build"].depends_on
    assert "s6_cargo_build" in by_id["s7_cargo_test"].depends_on


def test_planner_plan_defaults_to_fallback_7_steps():
    """未注入 LLM execute_fn 时，plan() 自动 fallback 到 7 步深拷贝。"""
    planner = Planner()
    steps = planner.plan(task_request=None, project_root="/tmp/dummy", doc=None)
    assert isinstance(steps, list)
    assert len(steps) == 7
    # 必须与常量内容一致，但不共享引用（深拷贝）
    for a, b in zip(steps, RULE_BASED_TETRIS_PLAN):
        assert a.id == b.id
        assert a.title == b.title
    steps[0].id = "mutated"
    assert RULE_BASED_TETRIS_PLAN[0].id != "mutated", "不得污染共享常量"


def test_planner_llm_path_success():
    """注入成功的 llm_execute_fn 时，plan() 返回 LLM 结果而非 fallback。"""
    custom = [
        Step(id="a1", title="自定义A", action="cmd"),
        Step(id="a2", title="自定义B", action="write_file", depends_on=["a1"]),
    ]

    def fake_execute(req, root, doc):
        return copy.deepcopy(custom)

    planner = Planner(llm_execute_fn=fake_execute)
    got = planner.plan(task_request="x", project_root="/tmp/yyy")
    assert [s.id for s in got] == ["a1", "a2"]


def test_planner_llm_path_invalid_results_fallback():
    """LLM 路径返回 None / 空列表 / 非 Step 列表 / 抛异常，均 fallback 到 7 步。"""
    invalid_outputs = [None, [], ["not-a-step"], Exception("boom")]
    for bad in invalid_outputs:

        def fake(req, root, doc, _bad=bad):
            if isinstance(_bad, Exception):
                raise _bad
            return _bad

        planner = Planner(llm_execute_fn=fake)
        got = planner.plan(task_request=1, project_root="/tmp/z")
        assert len(got) == 7, f"LLM 结果 {bad!r} 未触发 fallback"
        assert got[0].id == "s1_cargo_toml"


def test_step_dataclass_fields_defaults():
    """Step dataclass 字段默认值符合契约 (空依赖 / 空输出 / None payload)。"""
    s = Step(id="x", title="Y", action="cmd")
    assert s.depends_on == []
    assert s.expected_outputs == []
    assert s.payload_when_write_file is None
    assert s.cmd_when_cmd is None
    # 带参数构造
    s2 = Step(
        id="w",
        title="写文件",
        action="write_file",
        depends_on=["x"],
        expected_outputs=["Cargo.toml"],
        payload_when_write_file={"Cargo.toml": "[package]\n"},
    )
    assert s2.depends_on == ["x"]
    assert "Cargo.toml" in s2.payload_when_write_file


def test_valid_step_list_edge_cases():
    """_is_valid_step_list 对边界输入返回正确值。"""
    valid = [Step(id="1", title="T", action="cmd")]
    assert Planner._is_valid_step_list(valid) is True
    assert Planner._is_valid_step_list([]) is False
    assert Planner._is_valid_step_list(None) is False
    assert Planner._is_valid_step_list("abc") is False
    assert Planner._is_valid_step_list([Step(id="1", title="T", action="cmd"), "bad"]) is False
