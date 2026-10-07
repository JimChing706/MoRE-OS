"""R-07 回归测试：ITD 子任务（REQ）派发与需求级核验。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from more_core.core.requirement_verifier import (
    extract_checkpoints,
    verify_requirement,
)
from more_core.persistence.task_store import SQLiteTaskStore


# ---------------------------------------------------------------------------
# 需求核验器
# ---------------------------------------------------------------------------


def test_extract_checkpoints_mixes_code_and_cjk():
    tokens = extract_checkpoints(
        "服务端权威架构",
        "必须运行在 Rust 服务端，客户端只发送输入意图",
        "支持 WASD 移动与鼠标视角",
    )
    assert "WASD" in tokens
    assert any("服务端" == t for t in tokens)
    # 不应把整句当成一个 token
    assert not any(len(t) > 12 for t in tokens)


def test_extract_checkpoints_picks_up_paths():
    tokens = extract_checkpoints("暴露 shooter_server/src/main.rs 与 Cargo.toml")
    assert "shooter_server/src/main.rs" in tokens
    assert "Cargo.toml" in tokens


def test_verify_requirement_passes_when_covered():
    artifact = (
        "// 服务端 权威 状态\n"
        "pub fn handle_input(dir: WASD) {}\n"
        "// 客户端 发送 输入 意图；鼠标视角\n"
        "// shooter_server/src/main.rs\n"
    )
    v = verify_requirement(
        req_id="REQ-001",
        title="服务端权威架构",
        description="Rust 服务端，客户端只发送输入意图，支持 WASD 移动与鼠标视角",
        acceptance_criteria=["服务端持有权威状态"],
        artifact_text=artifact,
    )
    assert v.ok and v.status == "completed"
    assert v.coverage >= 0.4
    assert v.matched and v.evidence


def test_verify_requirement_fails_when_absent():
    v = verify_requirement(
        req_id="REQ-002",
        title="回合制竞技玩法",
        description="购买阶段、回合状态机、进攻防守计分",
        artifact_text="fn main() {}",
    )
    assert not v.ok and v.status == "failed"
    assert v.coverage == 0.0
    assert v.missing


def test_verify_requirement_without_checkpoints_is_not_blocking():
    v = verify_requirement(req_id="REQ-009", title="——", artifact_text="whatever")
    assert v.ok and v.status == "completed"


def test_verdict_dict_shape():
    v = verify_requirement(req_id="REQ-1", title="WASD", artifact_text="WASD")
    d = v.to_dict()
    assert set(d) >= {"req_id", "title", "status", "coverage", "matched", "missing", "evidence"}


# ---------------------------------------------------------------------------
# 存储：parent_id + list_children
# ---------------------------------------------------------------------------


def test_store_tracks_parent_and_lists_children(tmp_path):
    st = SQLiteTaskStore(tmp_path / "t.db")
    st.create_task("p1", {"title": "parent", "created_at": "now", "context": {"is_parent": True}})
    for i in (1, 2):
        st.create_task(
            f"p1-REQ-00{i}",
            {
                "title": f"REQ-00{i}",
                "created_at": "now",
                "context": {"parent_id": "p1", "requirement_id": f"REQ-00{i}"},
            },
        )
    kids = st.list_children("p1")
    assert [k["task_id"] for k in kids] == ["p1-REQ-001", "p1-REQ-002"]
    assert all(k["parent_id"] == "p1" for k in kids)
    assert st.list_children("nope") == []


def test_store_accepts_explicit_parent_id(tmp_path):
    st = SQLiteTaskStore(tmp_path / "t.db")
    st.create_task("c1", {"title": "child", "created_at": "now", "parent_id": "px"})
    assert [k["task_id"] for k in st.list_children("px")] == ["c1"]


# ---------------------------------------------------------------------------
# 端到端：执行器派发子任务并让父任务终态依赖子任务
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_dispatches_requirements_and_gates_parent(tmp_path):
    from more_core.core.config import Settings
    from more_core.core.guardrails import provenance_audit as _pa
    from more_core.core.guardrails.provenance_audit import ProvenanceLayer
    from more_core.runtime.orchestrator import MoRECore
    from conftest import _FakeLLMProvider
    from more_core.api.routers.tasks import _execute_task_background_v2

    settings = Settings(
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
    )
    core = MoRECore(settings)
    core.llm._providers["fake"] = _FakeLLMProvider()
    core.llm._fallback = ["fake"]

    store = SQLiteTaskStore(tmp_path / "tasks.db")
    import more_core.api.routers.tasks as tr_mod

    tr_mod._task_store = store
    _pa._default_layer = ProvenanceLayer(tmp_path / "prov.db")

    parent = "req-dispatch-test-001"
    store.create_task(
        parent,
        {
            "task_id": parent,
            "title": "Tetris Build",
            "type": "code_generation",
            "description": "build tetris project",
            "status": "pending",
            "progress": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "context": {"is_parent": True, "max_iterations": 1},
        },
    )
    # 子任务 1：产物（tetris 模板）里必然存在这些符号 → 应 completed
    store.create_task(
        f"{parent}-REQ-001",
        {
            "task_id": f"{parent}-REQ-001",
            "title": "REQ-001: Cargo 构建产物",
            "description": "输出 Cargo.toml 与 Makefile",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "context": {
                "parent_id": parent,
                "requirement_id": "REQ-001",
                "acceptance_criteria": ["存在 Cargo.toml"],
            },
        },
    )
    # 子任务 2：产物里绝不存在 → 应 failed
    store.create_task(
        f"{parent}-REQ-002",
        {
            "task_id": f"{parent}-REQ-002",
            "title": "REQ-002: 火箭发动机推力控制",
            "description": "implement rocket_thrust_controller 与 orbital_guidance 模块",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "context": {
                "parent_id": parent,
                "requirement_id": "REQ-002",
                "acceptance_criteria": ["rocket_thrust_controller 可调用"],
            },
        },
    )

    await _execute_task_background_v2(
        parent,
        {
            "task_id": parent,
            "title": "Tetris Build",
            "description": "build tetris project",
            "type": "code_generation",
            "priority": "medium",
            "context": {"max_iterations": 1},
        },
        core,
    )

    kids = {k["task_id"]: k for k in store.list_children(parent)}
    assert len(kids) == 2
    # 子任务不再停留在 pending
    assert all(k["status"] != "pending" for k in kids.values())
    assert kids[f"{parent}-REQ-002"]["status"] == "failed"
    assert kids[f"{parent}-REQ-002"]["result"]
    # 有子任务未达标 → 父任务不得报 completed
    parent_task = store.get_task(parent)
    assert parent_task["status"] == "failed", parent_task.get("error")
    assert any("REQ" in w for w in parent_task.get("warnings", []))
