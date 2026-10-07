"""Linux 加固沙箱测试（sandbox/linux_sandbox.py 覆盖补齐）。

当前平台为 macOS，故重点覆盖"非 Linux 回退"路径 + 通过 monkeypatch 模拟 Linux 的
unshare/cgroup 路径（不真实创建命名空间）。
"""

from __future__ import annotations

import asyncio

import pytest

from more_core.sandbox import linux_sandbox as ls
from more_core.sandbox.subprocess_sandbox import SandboxResult, SubprocessSandbox


# ---------------------------------------------------------------------------
# 平台探测 / 工厂
# ---------------------------------------------------------------------------


def test_is_linux_reflects_platform(monkeypatch):
    monkeypatch.setattr(ls.sys, "platform", "linux")
    assert ls.is_linux() is True
    monkeypatch.setattr(ls.sys, "platform", "darwin")
    assert ls.is_linux() is False


def test_cgroup_v2_available_reads_path(monkeypatch):
    class _Probe:
        exists_value = True

        def __init__(self, *_a, **_k):
            pass

        def exists(self) -> bool:
            return _Probe.exists_value

    monkeypatch.setattr(ls, "Path", _Probe)
    assert ls._cgroup_v2_available() is True
    _Probe.exists_value = False
    assert ls._cgroup_v2_available() is False


def test_create_sandbox_returns_base_on_non_linux(monkeypatch):
    monkeypatch.setattr(ls, "is_linux", lambda: False)
    sbx = ls.create_sandbox(timeout_s=5, memory_mb=64)
    assert isinstance(sbx, SubprocessSandbox)
    assert not isinstance(sbx, ls.LinuxSandbox)


def test_create_sandbox_returns_linux_variant(monkeypatch):
    monkeypatch.setattr(ls, "is_linux", lambda: True)
    sbx = ls.create_sandbox(timeout_s=5, memory_mb=64)
    assert isinstance(sbx, ls.LinuxSandbox)


def test_init_detects_capabilities(monkeypatch):
    monkeypatch.setattr(ls, "is_linux", lambda: True)
    monkeypatch.setattr(ls, "_cgroup_v2_available", lambda: True)
    monkeypatch.setattr(ls.shutil, "which", lambda _n: "/usr/bin/unshare")
    sbx = ls.LinuxSandbox()
    assert sbx._use_unshare is True and sbx._use_cgroup is True


# ---------------------------------------------------------------------------
# run：回退路径（非 Linux）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_falls_back_to_base_sandbox_when_no_unshare():
    sbx = ls.LinuxSandbox(timeout_s=5)
    assert sbx._use_unshare is False
    result = await sbx.run(["/bin/echo", "hi"])
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0 and "hi" in result.stdout


# ---------------------------------------------------------------------------
# run：模拟 Linux unshare 路径
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, out: bytes = b"ok", err: bytes = b"", rc: int = 0, hang: bool = False):
        self._out, self._err, self.returncode, self._hang = out, err, rc, hang
        self.killed = False

    async def communicate(self, stdin=None):
        if self._hang:
            raise asyncio.TimeoutError
        return self._out, self._err

    def kill(self):
        self.killed = True

    async def wait(self):
        return 0


@pytest.mark.asyncio
async def test_run_builds_unshare_command(monkeypatch):
    captured: dict = {}

    async def fake_exec(*argv, **kw):
        captured["argv"] = list(argv)
        captured["kw"] = kw
        return _FakeProc(out=b"hello\n")

    monkeypatch.setattr(ls.asyncio, "create_subprocess_exec", fake_exec)
    sbx = ls.LinuxSandbox(timeout_s=5, enable_network=False)
    sbx._use_unshare = True
    sbx._use_cgroup = False  # 跳过真实 cgroup 写入

    result = await sbx.run("echo hi")
    assert result.stdout == "hello\n" and result.exit_code == 0
    argv = captured["argv"]
    assert argv[:4] == ["unshare", "--pid", "--fork", "--mount-proc"]
    assert "--net" in argv, "默认应隔离网络"
    assert argv[-2:] == ["echo", "hi"]


@pytest.mark.asyncio
async def test_run_skips_net_isolation_when_enabled(monkeypatch):
    captured: dict = {}

    async def fake_exec(*argv, **kw):
        captured["argv"] = list(argv)
        return _FakeProc()

    monkeypatch.setattr(ls.asyncio, "create_subprocess_exec", fake_exec)
    sbx = ls.LinuxSandbox(enable_network=True)
    sbx._use_unshare = True
    sbx._use_cgroup = False
    await sbx.run(["true"])
    assert "--net" not in captured["argv"]


@pytest.mark.asyncio
async def test_run_timeout_marks_timed_out(monkeypatch):
    async def fake_exec(*argv, **kw):
        return _FakeProc(hang=True)

    monkeypatch.setattr(ls.asyncio, "create_subprocess_exec", fake_exec)
    sbx = ls.LinuxSandbox(timeout_s=1)
    sbx._use_unshare = True
    sbx._use_cgroup = False

    result = await sbx.run(["sleep", "99"])
    assert result.timed_out is True
    assert result.exit_code == -1
    assert "linux hardened" in result.stderr


# ---------------------------------------------------------------------------
# cgroup 管理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_cgroup_writes_limits(tmp_path):
    sbx = ls.LinuxSandbox(memory_mb=128)
    sbx._cgroup_root = tmp_path / "more_sandbox"
    cg = await sbx._setup_cgroup()

    assert cg.exists()
    assert (cg / "memory.max").read_text() == str(128 * 1024 * 1024)
    assert (cg / "pids.max").read_text() == "64"
    assert " " in (cg / "cpu.max").read_text()


@pytest.mark.asyncio
async def test_teardown_cgroup_kills_leftover_procs(tmp_path, monkeypatch):
    """真实 cgroup 的限额文件由内核管理（rmdir 可成功）；此处验证 kill 分支不抛异常。"""
    killed: list[int] = []
    monkeypatch.setattr(ls.os, "kill", lambda pid, sig: killed.append(pid))

    sbx = ls.LinuxSandbox()
    cg = tmp_path / "sbx_x"
    cg.mkdir()
    (cg / "cgroup.procs").write_text("12345\n999999999\n")
    await sbx._teardown_cgroup(cg)  # 不得抛异常

    assert 12345 in killed


@pytest.mark.asyncio
async def test_teardown_cgroup_missing_dir_is_safe(tmp_path):
    sbx = ls.LinuxSandbox()
    await sbx._teardown_cgroup(tmp_path / "nope")  # 不应抛异常
