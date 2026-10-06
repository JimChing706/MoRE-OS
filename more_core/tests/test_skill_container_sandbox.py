"""code.execute 容器化纵深防御（P1 / RR-1）测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from more_core.skills import CodeExecutionSkill


def _skill(**cfg) -> CodeExecutionSkill:
    return CodeExecutionSkill(cfg or None)


# ---------------------------------------------------------------------------
# 配置探测
# ---------------------------------------------------------------------------


def test_runtime_empty_when_not_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _n: None)
    assert _skill()._container_runtime() == ""


def test_runtime_from_env(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setenv("MORE_SKILL_CONTAINER_RUNTIME", "podman")
    assert _skill()._container_runtime() == "podman"


def test_runtime_from_config_takes_precedence(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setenv("MORE_SKILL_CONTAINER_RUNTIME", "docker")
    assert _skill(container_runtime="podman")._container_runtime() == "podman"


def test_image_from_env_and_config(monkeypatch):
    monkeypatch.setenv("MORE_SKILL_CONTAINER_IMAGE", "python:3.12-slim")
    assert _skill()._container_image() == "python:3.12-slim"
    assert _skill(container_image="myimg")._container_image() == "myimg"


# ---------------------------------------------------------------------------
# 容器命令构造（安全参数）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "language,interpreter,script",
    [("python", "python", "main.py"), ("javascript", "node", "main.js"), ("bash", "bash", "main.sh")],
)
def test_container_argv_security_flags(language, interpreter, script):
    argv = CodeExecutionSkill._container_argv("img", language)
    assert argv[:2] == ["run", "--rm"]
    for flag, value in (
        ("--network", "none"), ("--memory", "256m"), ("--cpus", "0.5"),
        ("--pids-limit", "64"),
    ):
        assert flag in argv and argv[argv.index(flag) + 1] == value
    assert "--read-only" in argv
    assert "-v" in argv and "<workdir>:/work:ro" in argv
    # 必须显式覆盖 ENTRYPOINT，否则镜像自带 entrypoint 会吞掉解释器命令
    assert "--entrypoint" in argv and argv[argv.index("--entrypoint") + 1] == interpreter
    assert argv[-2:] == ["img", f"/work/{script}"]


# ---------------------------------------------------------------------------
# 执行路径
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, out=b"ok\n", err=b"", rc=0, hang=False):
        self._out, self._err, self.returncode, self._hang = out, err, rc, hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            raise asyncio.TimeoutError
        return self._out, self._err

    def kill(self):
        self.killed = True

    async def wait(self):
        return 0


@pytest.mark.asyncio
async def test_run_in_container_mounts_script_readonly(monkeypatch):
    captured: dict = {}

    async def fake_exec(*argv, **kw):
        captured["argv"] = list(argv)
        # 在"调用时刻"捕获脚本确实被写入并被只读挂载
        mount = argv[argv.index("-v") + 1]
        host_dir = Path(mount.split(":")[0])
        captured["script_exists"] = (host_dir / "main.py").exists()
        captured["script_text"] = (host_dir / "main.py").read_text()
        return _FakeProc(out=b"42\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    s = _skill(container_image="img", container_runtime="docker")
    result = await s._run_in_container("docker", "img", "python", "print(42)", 5)

    assert result["sandbox_mode"] == "container"
    assert result["returncode"] == 0 and result["stdout"] == "42\n"
    mount = captured["argv"][captured["argv"].index("-v") + 1]
    assert mount.endswith(":/work:ro")
    assert captured["script_exists"] is True          # 脚本已写入挂载目录
    assert captured["script_text"] == "print(42)"      # 内容一致


@pytest.mark.asyncio
async def test_run_in_container_timeout(monkeypatch):
    async def fake_exec(*argv, **kw):
        return _FakeProc(hang=True)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    s = _skill(container_image="img")
    result = await s._run_in_container("docker", "img", "python", "x", 1)
    assert result["timed_out"] is True and "container timeout" in result["stderr"]


@pytest.mark.asyncio
async def test_run_in_container_missing_runtime(monkeypatch):
    async def fake_exec(*argv, **kw):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    s = _skill(container_image="img")
    result = await s._run_in_container("docker", "img", "python", "x", 1)
    assert result["returncode"] == 1 and "missing" in result["stderr"]


@pytest.mark.asyncio
async def test_run_code_prefers_container_when_configured(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    called: dict = {}

    async def fake_container(self, runtime, image, language, code, timeout):
        called["image"] = image
        return {"returncode": 0, "stdout": "from-container", "stderr": "",
                "timed_out": False, "sandboxed": True, "sandbox_mode": "container"}

    monkeypatch.setattr(CodeExecutionSkill, "_run_in_container", fake_container)
    s = _skill(container_image="img")
    result = await s._run_code("python", "print(1)", 5)
    assert called["image"] == "img"
    assert result["sandbox_mode"] == "container"


@pytest.mark.asyncio
async def test_execute_reports_secure_sandbox_by_default():
    s = _skill()
    result = await s.execute({"code": "print(1 + 1)", "language": "python", "timeout": 10})
    assert result.success is True
    assert result.metadata["sandbox_mode"] == "secure_sandbox"
    assert result.metadata["sandboxed"] is True


@pytest.mark.asyncio
async def test_execute_reports_container_mode(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")

    async def fake_container(self, runtime, image, language, code, timeout):
        return {"returncode": 0, "stdout": "42\n", "stderr": "",
                "timed_out": False, "sandboxed": True, "sandbox_mode": "container"}

    monkeypatch.setattr(CodeExecutionSkill, "_run_in_container", fake_container)
    result = await _skill(container_image="img").execute(
        {"code": "print(42)", "language": "python", "timeout": 10}
    )
    assert result.success is True
    assert result.metadata["sandbox_mode"] == "container"
