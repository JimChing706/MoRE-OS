"""R-10 回归测试：沙箱策略加固（AST 判定 / 全 argv 检查 / 路径白名单 / env 净化）。"""

from __future__ import annotations

import pytest

from more_core.sandbox.policy import SandboxPolicy
from more_core.sandbox.secure_sandbox import (
    SandboxConfig,
    SecureSandbox,
    SecurityLevel,
)
from more_core.sandbox.subprocess_sandbox import SubprocessSandbox


@pytest.fixture()
def policy():
    return SandboxPolicy()


@pytest.fixture()
def sandbox():
    return SecureSandbox(
        SubprocessSandbox(timeout_s=10, memory_mb=128),
        SandboxConfig(security_level=SecurityLevel.BASIC, timeout_s=10),
    )


# ---------------------------------------------------------------------------
# AST 判定：旧子串实现可绕过的形态必须被拦
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,why",
    [
        ("import os; os.system('rm -rf /')", "直接调用"),
        ("getattr(__import__('os'), 'system')('rm -rf /')", "反射式导入"),
        ("import subprocess as s; s.run(['rm','-rf','/'])", "别名导入"),
        ("from os import system; system('id')", "from-import 别名"),
        ("from subprocess import run; run(['id'])", "from-import 别名"),
        ("eval(compile('1+1','<x>','eval'))", "动态执行"),
        ("import socket; socket.create_connection(('1.1.1.1',80))", "网络"),
        ("import ctypes; ctypes.CDLL('libc.so.6')", "原生互操作"),
        ("import shutil; shutil.rmtree('/tmp/x')", "破坏性文件操作"),
    ],
)
def test_ast_policy_blocks_bypass_forms(policy, code, why):
    violations = policy.scan_python(code)
    assert violations, f"{why} 未被拦截：{code}"


@pytest.mark.parametrize(
    "code",
    [
        "import statistics; print(statistics.mean([1,2,3]))",
        "import math\nprint(math.sqrt(16))",
        "from collections import Counter\nprint(Counter('aab'))",
        "import json\nprint(json.dumps({'a': 1}))",
        "sorted([3,1,2], key=lambda x: x)",
    ],
)
def test_ast_policy_allows_benign_code(policy, code):
    assert policy.scan_python(code) == []


def test_syntax_error_is_blocked_not_ignored(policy):
    violations = policy.scan_python("def broken(:\n  pass")
    assert violations and "cannot parse" in violations[0]


def test_dangerous_import_is_flagged_even_without_call(policy):
    assert policy.scan_python("import subprocess")


def test_import_allowlist_uses_ast_not_line_prefix(policy):
    # 旧实现按行首匹配，``import os as o`` 之类可绕过
    assert "subprocess" in policy.validate_imports("import subprocess as s")
    assert "subprocess" in policy.validate_imports("from subprocess import run")
    assert policy.validate_imports("import statistics") == []


# ---------------------------------------------------------------------------
# 命令行：全 argv 检查
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /tmp/x",
        "sudo id",
        "echo hi; rm -rf /",
        "python3 -c 'import os'",
        "bash -c 'id'",
        "sh -c 'id'",
        "/usr/bin/rm -f /tmp/x",
        "env LD_PRELOAD=/tmp/evil.so ls",
    ],
)
def test_command_policy_blocks(policy, cmd):
    assert policy.check_command(cmd), f"未拦截：{cmd}"


@pytest.mark.parametrize(
    "cmd",
    ["ls -la", "echo hello", "cat README.md", "python3 script.py"],
)
def test_command_policy_allows_normal(policy, cmd):
    assert policy.check_command(cmd) == []


# ---------------------------------------------------------------------------
# SecureSandbox 集成
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_allows_benign_python(sandbox):
    r = await sandbox.run_python("import statistics\nprint(statistics.mean([1,2,3]))")
    assert r.exit_code == 0
    assert "2" in r.stdout


@pytest.mark.asyncio
async def test_sandbox_blocks_os_system(sandbox):
    r = await sandbox.run_python("import os; os.system('id')")
    assert r.exit_code == -1
    assert "blocked" in r.stderr.lower()


@pytest.mark.asyncio
async def test_sandbox_blocks_reflection_bypass(sandbox):
    r = await sandbox.run_python("getattr(__import__('os'), 'system')('id')")
    assert r.exit_code == -1
    assert "blocked" in r.stderr.lower()


@pytest.mark.asyncio
async def test_sandbox_blocks_blocked_command_and_env_injection(sandbox):
    r1 = await sandbox.run("sudo id")
    assert r1.exit_code == -1 and "blocked" in r1.stderr.lower()
    r2 = await sandbox.run("env LD_PRELOAD=/tmp/evil.so ls")
    assert r2.exit_code == -1 and "blocked" in r2.stderr.lower()


@pytest.mark.asyncio
async def test_sandbox_default_cwd_is_applied(sandbox):
    """未传 cwd 时也必须落到沙箱默认目录（否则 allowed_paths 形同虚设）。"""
    r = await sandbox.run("pwd")
    assert r.exit_code == 0
    assert "more_os_sbx" in r.stdout


@pytest.mark.asyncio
async def test_sandbox_rejects_cwd_outside_allowlist(sandbox):
    r = await sandbox.run("pwd", cwd="/etc")
    assert r.exit_code == -1
    assert "not in allowed paths" in r.stderr


def test_path_prefix_check_rejects_sibling_dir(sandbox):
    ok_tmp, _ = sandbox._check_path("/tmp/ok")
    bad, reason = sandbox._check_path("/tmpfoo/evil")
    assert ok_tmp is True
    assert bad is False, "存在 /tmp 前缀误判"
    assert "not in allowed paths" in reason


def test_env_sanitisation_strips_injection_vars(sandbox):
    cleaned = sandbox._sanitize_env(
        {"PATH": "/usr/bin", "LD_PRELOAD": "/tmp/x.so", "PYTHONPATH": "/evil"}
    )
    assert cleaned == {"PATH": "/usr/bin"}
    assert sandbox._sanitize_env(None) is None


# ---------------------------------------------------------------------------
# STRICT 级别：额外强制导入白名单
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_level_enforces_import_allowlist():
    strict = SecureSandbox(
        SubprocessSandbox(timeout_s=10, memory_mb=128),
        SandboxConfig(security_level=SecurityLevel.STRICT, timeout_s=10),
    )
    # statistics 在白名单内 → 放行
    ok = await strict.run_python("import statistics\nprint(statistics.mean([1,2]))")
    assert ok.exit_code == 0
    # os.path 在白名单内 → 放行
    ok_path = await strict.run_python("import os.path\nprint(os.path.join('a','b'))")
    assert ok_path.exit_code == 0
    # 但 import os 不在白名单内（白名单有 os.path ≠ 允许整个 os）→ STRICT 下拦截
    blocked = await strict.run_python("import os\nprint(os.getcwd())")
    assert blocked.exit_code == -1
    assert "disallowed imports" in blocked.stderr


@pytest.mark.asyncio
async def test_basic_level_allows_non_allowlisted_safe_imports():
    """BASIC 不强制导入白名单，避免误杀代码生成回路里正常的标准库导入。"""
    basic = SecureSandbox(
        SubprocessSandbox(timeout_s=10, memory_mb=128),
        SandboxConfig(security_level=SecurityLevel.BASIC, timeout_s=10),
    )
    r = await basic.run_python("import os.path\nprint(os.path.join('a','b'))")
    assert r.exit_code == 0
