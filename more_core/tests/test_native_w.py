"""单测：Writer (writer.py)

目标：覆盖安全白名单前缀校验、.. 穿越检测、ProvenanceViolation 0 写盘、
审计 JSONL 日志、build_tetris_payload_map 输出文件、src/tests.rs ≥ 24 个 #[test]。
共 ≥ 5 tests。
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
from pathlib import Path

import pytest

from more_core.core.native_executor.writer import (
    Writer,
    ProvenanceViolation,
)
from more_core.core.native_executor.planner import Step


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_tmp_project() -> Path:
    """在 /tmp/more_os_native_runs/ 下创建临时 project 根目录（白名单内）。"""
    base = Path("/tmp/more_os_native_runs")
    base.mkdir(parents=True, exist_ok=True)
    td = Path(tempfile.mkdtemp(prefix="proj_", dir=str(base)))
    return td


def _make_steps_with_payload(project_root, rel_to_content):
    """构造一个 write_file 动作 Step（带 payload）。"""
    return [
        Step(
            id="test_step",
            title="单测写入步骤",
            action="write_file",
            payload_when_write_file=dict(rel_to_content),
        )
    ]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_provenance_violation_dotdot_path_writes_zero(tmp_path):
    """目标路径包含 '..' 时立即抛 ProvenanceViolation，且保证 0 写盘。"""
    project_root = _make_tmp_project()
    writer = Writer(work_root=str(project_root))
    # 构造相对路径包含 '..'，即解析后会跳出 project_root
    bad = {"../../etc/pwn.txt": "evil"}
    steps = _make_steps_with_payload(str(project_root), bad)
    # 记录 pre-write 状态（project_root 下除了 audit，应 0 个内容文件）
    files_before = {
        str(p) for p in project_root.rglob("*") if p.is_file() and not str(p).endswith(".jsonl")
    }
    with pytest.raises(ProvenanceViolation) as excinfo:
        writer.apply(str(project_root), steps, task_id="t_evil")
    # 无论由「.. 穿越」规则还是「/tmp/ 非白名单」规则触发都可，必须是 ProvenanceViolation
    assert isinstance(excinfo.value, ProvenanceViolation)
    # 0 写盘断言：project_root 下不该产生任何内容文件（审计日志 .jsonl 除外）
    files_after = {
        str(p) for p in project_root.rglob("*") if p.is_file() and not str(p).endswith(".jsonl")
    }
    assert files_after == files_before, (
        f"0 写盘被破坏：新增内容文件 {sorted(files_after - files_before)}"
    )
    # 且 /tmp/more_os_native_runs/etc/pwn.txt 绝对不应存在
    assert not Path("/tmp/more_os_native_runs/etc/pwn.txt").exists()
    assert not (project_root / ".." / ".." / "etc" / "pwn.txt").exists()


def test_provenance_violation_tmp_non_whitelist_prefix():
    """目标路径在 /tmp/ 下但非 /tmp/more_os_native_runs/ 子目录，立即拒绝。"""
    project_root = _make_tmp_project()
    writer = Writer(work_root=str(project_root))
    # 构造 Step 用绝对路径 payload（normpath 后直接指向 /tmp/evil.txt）
    steps = [
        Step(
            id="x", title="x", action="write_file", payload_when_write_file={"/tmp/evil.txt": "bad"}
        )
    ]
    with pytest.raises(ProvenanceViolation) as excinfo:
        writer.apply(str(project_root), steps, task_id="t_tmpbad")
    assert "/tmp/" in str(excinfo.value)
    assert not Path("/tmp/evil.txt").exists()


def test_provenance_violation_project_root_outside_whitelist():
    """project_root 本身不在白名单内 → 即使相对路径合法也会拒绝。"""
    # 使用系统临时目录的纯 tmp_path（pytest 提供，不在白名单）
    outside = Path(tempfile.mkdtemp(prefix="not_whitelist_", dir="/tmp"))
    writer = Writer(work_root=str(outside))
    steps = _make_steps_with_payload(str(outside), {"a.txt": "hi"})
    with pytest.raises(ProvenanceViolation):
        writer.apply(str(outside), steps, task_id="t_outside")


def test_apply_writes_all_tetris_files_and_audit_jsonl():
    """正常场景：写入 5 个俄罗斯方块核心文件 + 审计 JSONL 每条记录包含 size/sha256。"""
    project_root = _make_tmp_project()
    writer = Writer(work_root=str(project_root))
    payload = writer.build_tetris_payload_map()
    assert set(payload.keys()) >= {
        "Cargo.toml",
        "src/lib.rs",
        "src/tests.rs",
        "frontend/index.html",
        "js/tetris.js",
    }
    steps = [Step(id="s_all", title="写全部", action="write_file", payload_when_write_file=payload)]
    written = writer.apply(str(project_root), steps, task_id="t_all_ok", template_key="tetris")
    # 5 个文件确实落盘
    for rel, abs_path in written.items():
        assert Path(abs_path).is_file(), f"{rel} 未写出"
        assert Path(abs_path).stat().st_size > 0
    # audit JSONL 行数 ≥ 5，且每行都是合法 JSON、含 sha256 字段
    audit_root = Path("/tmp/more_os_native_runs/_audit")
    audit_file = audit_root / "t_all_ok.jsonl"
    assert audit_file.is_file(), f"审计文件不存在: {audit_file}"
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 5
    for line in lines:
        rec = json.loads(line)
        assert "sha256_hex" in rec
        assert len(rec["sha256_hex"]) == 64
        assert "size_bytes" in rec
        assert rec["task_id"] == "t_all_ok"


def test_tetris_tests_rs_contains_at_least_24_test_attrs():
    """src/tests.rs 必须包含 ≥ 24 个 #[test] 标注。"""
    project_root = _make_tmp_project()
    writer = Writer(work_root=str(project_root))
    content = writer.build_tetris_payload_map()["src/tests.rs"]
    count = content.count("#[test]")
    assert count >= 24, f"src/tests.rs 只有 {count} 个 #[test]，需 ≥ 24"


def test_lib_rs_contains_srs_kicks_const_or_srs_kick_fn():
    """src/lib.rs 必须包含 SRS_KICKS 常量 或 srs_kick() 函数定义。"""
    project_root = _make_tmp_project()
    writer = Writer(work_root=str(project_root))
    content = writer.build_tetris_payload_map()["src/lib.rs"]
    has_const = "SRS_KICKS" in content and ("pub const" in content or "const SRS_KICKS" in content)
    has_fn = "fn srs_kick" in content
    assert has_const or has_fn, "src/lib.rs 必须包含 SRS_KICKS 常量或 srs_kick() 函数"


def test_workdata_prefix_also_allowed():
    """白名单前缀 2：{work_root}/more_core/data/native_runs/ 内路径应当被允许。"""
    # 在真实 more_core 目录不存在时，使用 Writer._auto 机制不可靠，因此这里用 _assert_safe_path API 间接测
    # 注：白名单 2 的目录名在运行时拼接；我们直接构造一个满足 workdata_prefix 的 path 并 inject
    import tempfile as _tf

    tmp_work = Path(_tf.mkdtemp(prefix="work_", dir="/tmp/more_os_native_runs"))
    # 手动创建 workdata 目录
    wd = tmp_work / "more_core" / "data" / "native_runs"
    wd.mkdir(parents=True, exist_ok=True)
    writer = Writer(work_root=str(tmp_work))
    # 构造一个内部路径 project_root = workdata/sub
    project_root = wd / "sub1"
    project_root.mkdir(parents=True, exist_ok=True)
    steps = _make_steps_with_payload(str(project_root), {"README.md": "ok"})
    audit_root = wd / "_audit"
    # 正常情况下不会抛异常（README.md 在 generic manifest 内）
    written = writer.apply(
        str(project_root), steps, task_id="t_workdata", audit_root=str(audit_root)
    )
    assert "README.md" in written
    assert (project_root / "README.md").read_text() == "ok"
