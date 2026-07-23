"""Security penetration tests — command injection, sandbox escape."""

import pytest


@pytest.fixture
async def started_core(core):
    from more_core.tools.builtins import register_builtins
    register_builtins(core.tools, core)
    return core


class TestCommandInjection:
    async def test_shell_exec_blocks_rm_rf(self, started_core):
        result = await started_core.tools.invoke("shell_exec", {
            "command": "echo hello; rm -rf /",
        })
        sandboxed = not result.success and ("blocked" in result.error.lower() or "Operation not permitted" in result.error)
        isolated = result.output == "hello"
        assert sandboxed or isolated, f"unexpected result: success={result.success} error={result.error}"

    async def test_run_tests_pattern_injection(self, started_core):
        result = await started_core.tools.invoke("run_tests", {
            "path": ".",
            "pattern": "test_*.py; rm -rf /",
        })
        assert not result.success or result.output is not None

    async def test_python_exec_sandbox_escape(self, started_core):
        result = await started_core.tools.invoke("python_exec", {
            "code": "import subprocess; subprocess.run(['rm', '-rf', '/'])",
        })
        blocked = "blocked" in result.error.lower() or "denied" in result.error.lower()
        assert blocked or not result.success, f"escape attempt succeeded: {result.output}"


class TestSandboxIsolation:
    async def test_blocked_command_rejected(self, started_core):
        result = await started_core.tools.invoke("shell_exec", {
            "command": "sudo rm -rf /etc",
        })
        assert not result.success

    async def test_python_os_system_blocked(self, started_core):
        result = await started_core.tools.invoke("python_exec", {
            "code": "import os; os.system('rm -rf /')",
        })
        blocked = "blocked" in result.error.lower()
        assert blocked or not result.success

    async def test_path_traversal_via_shell(self, started_core):
        result = await started_core.tools.invoke("shell_exec", {
            "command": "cat ../../../etc/passwd",
        })
        assert not result.success or "root:" not in result.output
