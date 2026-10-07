"""单测：Validator (validator.py)

目标：覆盖 4 条标准命令调用、retries=3 重试循环、
ValidationResult pass 聚合、artifacts 归档路径解析、_run_with_retries 行为。
共 ≥ 5 tests。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
from pathlib import Path

from more_core.core.native_executor.validator import (
    CommandRun,
    ValidationResult,
    Validator,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _fake_runner_factory(behavior_map):
    """构造一个 _run_hook，按 cmd[0] 从 behavior_map 取返回行为。

    behavior_map:
      key: str (cmd 的第一个 token 或特殊 'build'/'test'/'tar'/'unzip')
      value: 可以是
        - int: 固定 returncode，stdout="" stderr=""
        - dict(rc=int, stdout=str, stderr=str, dur_ms=int)
        - callable(cmd, cwd, attempt) -> CommandRun（含"前 N 次失败"等高级行为）
    """

    def _hook(cmd, cwd, attempt):
        key0 = cmd[0]
        # 从整条命令中推断更具体的 key
        if key0 == "cargo" and "build" in cmd:
            key = "build"
        elif key0 == "cargo" and "test" in cmd:
            key = "test"
        elif key0 == "tar":
            key = "tar"
        elif key0 == "unzip":
            key = "unzip"
        else:
            key = key0
        spec = behavior_map.get(key, 0)
        if callable(spec):
            return spec(cmd, cwd, attempt)
        if isinstance(spec, dict):
            return CommandRun(
                cmd=list(cmd),
                cwd=cwd,
                attempt=attempt,
                returncode=spec.get("rc", 0),
                stdout=spec.get("stdout", ""),
                stderr=spec.get("stderr", ""),
                duration_ms=spec.get("dur_ms", 1),
            )
        return CommandRun(
            cmd=list(cmd),
            cwd=cwd,
            attempt=attempt,
            returncode=int(spec),
            stdout="",
            stderr="",
            duration_ms=1,
        )

    return _hook


def _tmp_proj():
    return Path(tempfile.mkdtemp(prefix="vp_", dir="/tmp/more_os_native_runs"))


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_validate_4_commands_all_pass():
    """4 条命令全部通过 → pass_=True，command_results 长度 =4。"""
    hook = _fake_runner_factory({"build": 0, "test": 0, "tar": 0, "unzip": 0})
    v = Validator(_run_hook=hook)
    proj = _tmp_proj()
    arts = {
        "tar_gz": "/tmp/more_os_native_runs/dummy.tar.gz",
        "zip": "/tmp/more_os_native_runs/dummy.zip",
    }
    result = v.validate(str(proj), arts)
    assert result.pass_ is True
    assert result.total_commands == 4
    assert result.passed_commands == 4


def test_validate_cargo_build_failure_makes_pass_false():
    """cargo build 失败 → pass_=False，其他命令仍被执行。"""
    hook = _fake_runner_factory({"build": 1, "test": 0, "tar": 0, "unzip": 0})
    v = Validator(_run_hook=hook)
    proj = _tmp_proj()
    result = v.validate(str(proj), {"tar_gz": "a.tar.gz", "zip": "b.zip"})
    assert result.pass_ is False
    assert result.passed_commands == 3
    assert result.command_results[0].returncode == 1  # build


def test_validate_retries_3_times_on_continuous_failure():
    """单条命令连续失败时，会重试到 3 次（最后一次 attempt=3）。"""
    call_log = []

    def always_fail(cmd, cwd, attempt):
        call_log.append((tuple(cmd), attempt))
        return CommandRun(
            cmd=list(cmd),
            cwd=cwd,
            attempt=attempt,
            returncode=1,
            stdout="",
            stderr=f"fail at {attempt}",
            duration_ms=1,
        )

    def success_and_log(cmd, cwd, attempt):
        call_log.append((tuple(cmd), attempt))
        return CommandRun(
            cmd=list(cmd),
            cwd=cwd,
            attempt=attempt,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
        )

    hook = _fake_runner_factory(
        {"build": always_fail, "test": success_and_log, "tar": 0, "unzip": 0}
    )
    v = Validator(retries=3, initial_backoff_s=0.001, _run_hook=hook)
    proj = _tmp_proj()
    result = v.validate(str(proj), {})  # 没提供归档，只跑 cargo build+test=2 条
    # build 会被调用 3 次
    build_calls = [c for c in call_log if "build" in c[0]]
    assert len(build_calls) == 3, f"预期调用 3 次 build，实际 {len(build_calls)}: {build_calls}"
    assert build_calls[0][1] == 1
    assert build_calls[-1][1] == 3
    # test 只需要 1 次（成功）
    test_calls = [c for c in call_log if "test" in c[0]]
    assert len(test_calls) == 1
    # 结果 pass=False
    assert result.pass_ is False


def test_validate_retry_succeeds_on_second_attempt():
    """命令第 2 次尝试成功 → 总共调用 2 次，returncode=0，attempt=2。"""
    state = {"count": 0}

    def fail_first(cmd, cwd, attempt):
        state["count"] += 1
        rc = 0 if state["count"] >= 2 else 1
        return CommandRun(
            cmd=list(cmd),
            cwd=cwd,
            attempt=attempt,
            returncode=rc,
            stdout=f"a{attempt}",
            stderr="",
            duration_ms=1,
        )

    hook = _fake_runner_factory({"build": fail_first, "test": 0, "tar": 0, "unzip": 0})
    v = Validator(retries=3, initial_backoff_s=0.001, _run_hook=hook)
    proj = _tmp_proj()
    result = v.validate(str(proj), {"tar_gz": "x", "zip": "y"})
    assert result.pass_ is True
    # build 那条的最后一次 attempt 是 2
    build_run = result.command_results[0]
    assert build_run.attempt == 2
    assert build_run.returncode == 0
    assert state["count"] == 2


def test_validate_finds_artifacts_by_suffix_when_key_missing():
    """artifacts key 不是 'tar_gz'/'zip' 但 value 以 .tar.gz/.zip 结尾 → 也能触发归档校验。"""
    hook_log = []

    def record(cmd, cwd, attempt):
        hook_log.append(tuple(cmd))
        return CommandRun(
            cmd=list(cmd),
            cwd=cwd,
            attempt=attempt,
            returncode=0,
            stdout="",
            stderr="",
            duration_ms=1,
        )

    hook = _fake_runner_factory({"build": 0, "test": 0, "tar": record, "unzip": record})
    v = Validator(_run_hook=hook)
    proj = _tmp_proj()
    # 用非标准 key，但 value 带正确后缀
    arts = {"pkg_a": "/tmp/more_os_native_runs/p.tar.gz", "pkg_b": "/tmp/more_os_native_runs/q.zip"}
    result = v.validate(str(proj), arts)
    assert result.pass_ is True
    assert result.total_commands == 4
    # tar/unzip 都被实际调用过
    cmds_flat = []
    for run in result.command_results:
        cmds_flat.extend(run.cmd)
    assert "tzf" in cmds_flat or any("tar" in r.cmd for r in result.command_results)
    assert any("unzip" in r.cmd for r in result.command_results)


def test_validation_result_helper_methods():
    """ValidationResult.stdout_of / stderr_of / passed_commands / total_commands 边角行为。"""
    r = ValidationResult(pass_=False)
    r.command_results.append(
        CommandRun(
            cmd=["a"],
            cwd="/",
            attempt=1,
            returncode=1,
            stdout="out-a",
            stderr="err-a",
            duration_ms=1,
        )
    )
    r.command_results.append(
        CommandRun(
            cmd=["b"],
            cwd="/",
            attempt=1,
            returncode=0,
            stdout="out-b",
            stderr="",
            duration_ms=1,
        )
    )
    assert r.total_commands == 2
    assert r.passed_commands == 1
    assert r.stdout_of(0) == "out-a"
    assert r.stderr_of(0) == "err-a"
    assert r.stdout_of(1) == "out-b"
    assert r.stdout_of(999) == ""
    assert r.stderr_of(-1) == ""


def test_validate_missing_archives_skips_tar_unzip_only_runs_2_cmds():
    """artifacts 为空或不包含 tar/zip → 只运行 cargo build + test，共 2 条命令。"""
    hook = _fake_runner_factory({"build": 0, "test": 0})
    v = Validator(_run_hook=hook)
    proj = _tmp_proj()
    result = v.validate(str(proj), {})
    assert result.total_commands == 2
    assert result.pass_ is True
    result2 = v.validate(str(proj), {"something": "/else"})
    assert result2.total_commands == 2
