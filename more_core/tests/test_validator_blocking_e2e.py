"""I1/I2 集成测试：装配链 E2E — CS writer 无 tetris + bad_cargo 阻断。

Task6 Step1: RED→GREEN。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio


CS_ITD_DOC = """---
title: CS 风格第一人称射击游戏
type: code_generation
tags: [shooter, cs, fps, rust]
---
# Executive Summary
使用 Rust + axum + WebGL 开发 CS 风格射击游戏，支持联网对战。

## REQ-001 基础架构
Rust workspace 包含 shooter_core / shooter_server 两 crate。
## REQ-002 游戏逻辑
玩家移动、射击、碰撞检测。
## REQ-003 前端界面
React + Vite + Three.js 3D 渲染。
## REQ-004 部署交付
Dockerfile + docker-compose 一键部署。
"""

TETRIS_ITD_DOC = """---
title: 俄罗斯方块消除游戏
type: code_generation
tags: [tetris]
---
# Executive Summary
经典俄罗斯方块 7 Bag 随机算法。
## REQ-001 游戏玩法
左右移动、旋转、消除、计分。
"""


class _FakeCore:
    """MoRECore 替身 — _execute_task_background_v2 当前未使用 core。"""

    pass


def _fresh_task_store(tmp_path, task_id, status="pending"):
    """重置 task_store db，写入初始 task 记录。"""
    db = tmp_path / "tasks_e2e.db"
    if db.exists():
        db.unlink()
    from more_core.persistence.task_store import SQLiteTaskStore

    store = SQLiteTaskStore(str(db))
    info = {
        "type": "code_generation",
        "plugin_type": None,
        "query": task_id,
        "context": {},
        "title": task_id,
        "description": task_id,
        "status": status,
        "progress": 0,
        "current_step": "pending",
        "artifacts": [],
        "warnings": [],
        "result": None,
        "error": None,
    }
    store.create_task(task_id, info)
    # Monkey-patch tasks.py module-level _task_store
    from more_core.api.routers import tasks as tasks_mod

    tasks_mod._task_store = store
    return store


def test_sync_executor_cs_no_tetris_and_ok_completed(tmp_path, monkeypatch):
    """I1: CS ITD 分派 → writer 无 tetris，状态正确。

    注意：由于 sandbox 中 cargo 未安装，3A Validator 将 fail → HARD_BLOCK
    我们仅断言 writer phase 产物中无 tetris 路径，不校验最终 completed/failed。
    """
    from more_core.api.routers.tasks import _execute_task_background_v2
    from more_core.core.guardrails.provenance_audit import ProvenanceLayer

    task_id = "t_e2e_cs_ok"
    store = _fresh_task_store(tmp_path, task_id)

    # 使用独立 provenance DB
    prov_db = tmp_path / f"prov_{task_id}.db"
    if prov_db.exists():
        prov_db.unlink()
    layer = ProvenanceLayer(str(prov_db))
    import more_core.core.guardrails.provenance_audit as prov_mod

    def _get():
        return layer

    monkeypatch.setattr(prov_mod, "get_default_layer", _get)

    task_info = {
        "task_id": task_id,
        "title": "CS 射击游戏",
        "description": "CS 风格第一人称射击游戏 Rust+前端",
        "type": "code_generation",
        "context": {"itd_content": CS_ITD_DOC},
    }

    asyncio.run(_execute_task_background_v2(task_id, task_info, _FakeCore()))

    task = store.get_task(task_id)
    assert task is not None
    artifacts = task.get("artifacts") or []

    # 找 writer phase 产物
    writer_art = None
    for a in artifacts:
        if isinstance(a, dict) and a.get("phase") == "writer":
            writer_art = a
            break
    assert writer_art is not None, f"未找到 writer 阶段 artifacts，全量: {artifacts}"
    assert writer_art.get("template_key") == "cs_shooter", (
        f"分派错误: {writer_art.get('template_key')}"
    )
    written = writer_art.get("files_written") or []
    for p in written:
        assert "tetris" not in p.lower(), f"CS writer 泄漏 tetris 路径: {p}"
    # 关键路径必须存在（来自 CSShooterWriterMixin manifest）
    written_set = set(written)
    assert any(p.startswith("shooter_core/") for p in written_set), "缺少 shooter_core/ 目录"
    assert any(p.startswith("shooter_server/") for p in written_set), "缺少 shooter_server/ 目录"
    assert any(p.startswith("frontend/") for p in written_set), "缺少 frontend/ 目录"
    assert "README.md" in written_set

    # provenance: writer + final 记录存在
    records = layer.list_records(task_id)
    phases = [
        r.get("payload", {}).get("phase") for r in records if isinstance(r.get("payload"), dict)
    ]
    assert "writer" in phases, f"phases={phases}"
    assert "final" in phases, f"缺失 phase=final: {phases}"
    # 审计阻断状态（可能因 cargo 缺失为 True，但 writer payload 是合法的）
    report = layer.audit(task_id)
    assert report.files_written_count > 0, (
        f"provenance audit 未统计到任何写入文件：{report.to_dict()}"
    )
    # final_status 应已写入
    any_final = any(
        isinstance(r.get("payload"), dict) and r["payload"].get("phase") == "final" for r in records
    )
    assert any_final, "final provenance 双写兜底失败"


def test_sync_executor_bad_cargo_blocks_release(tmp_path, monkeypatch):
    """I2: inject_bad_cargo_toml → 3A Validator fail → deliverable_blocked=True
    status=failed progress≤90 error=标准化文案 audit_blocked=True
    """
    from more_core.api.routers.tasks import _execute_task_background_v2
    from more_core.core.guardrails.provenance_audit import ProvenanceLayer

    task_id = "t_e2e_bad_cargo"
    store = _fresh_task_store(tmp_path, task_id)

    prov_db = tmp_path / f"prov_{task_id}.db"
    if prov_db.exists():
        prov_db.unlink()
    layer = ProvenanceLayer(str(prov_db))
    import more_core.core.guardrails.provenance_audit as prov_mod

    def _get():
        return layer

    monkeypatch.setattr(prov_mod, "get_default_layer", _get)

    task_info = {
        "task_id": task_id,
        "title": "Tetris (bad cargo toml)",
        "description": "Tetris 俄罗斯方块游戏 Rust+前端",
        "type": "code_generation",
        "context": {
            "itd_content": TETRIS_ITD_DOC,
            "inject_bad_cargo_toml": True,
        },
    }

    asyncio.run(_execute_task_background_v2(task_id, task_info, _FakeCore()))

    task = store.get_task(task_id)
    assert task is not None

    # 1) provenance 审计 deliverable_blocked=True
    report = layer.audit(task_id)
    assert report.deliverable_blocked is True, (
        f"bad_cargo 未阻断！warnings={report.warnings} latest={report.latest_payload}"
    )

    # 2) status endpoint override → status=failed progress≤90
    report2, new_status, new_progress = layer.audit_with_status_override(
        task_id,
        raw_status=task.get("status", "unknown"),
        raw_progress=int(task.get("progress", 0) or 0),
    )
    assert new_status == "failed", f"override 后 status={new_status}（应为 failed）"
    assert new_progress <= 90, f"override 后 progress={new_progress}（应≤90）"

    # 3) warnings 含阻断说明（标准化错误告警日志）
    all_warnings = list(task.get("warnings") or []) + list(report.warnings)
    joined = " | ".join(all_warnings)
    assert any(
        ("hard_block" in w.lower() or "blocked" in w.lower() or "validation" in w.lower())
        for w in all_warnings
    ), f"阻断告警缺失！warnings={joined}"

    # 4) artifacts 中 aggregate.should_block_release=True
    artifacts = task.get("artifacts") or []
    agg_art = None
    for a in artifacts:
        if isinstance(a, dict) and a.get("phase") == "aggregate":
            agg_art = a
            break
    # cargo 未安装时 3A 直接 fail → aggregate 应该 fail 且 block
    # 如果 cargo 可用，则 bad Cargo.toml 也将 fail → 两种情形下都应 block
    if agg_art is not None:
        assert agg_art.get("should_block_release") is True, f"aggregate 未阻断：{agg_art}"
        assert agg_art.get("blocking_level") == "hard_block"

    # 5) task_store error 字段有标准化文案（如果 verify_ok=False 时）
    err = task.get("error") or ""
    if err:
        assert (
            "deliverable blocked" in err.lower()
            or "validation" in err.lower()
            or "hard" in err.lower()
        ), f"error 文案未标准化: {err}"
