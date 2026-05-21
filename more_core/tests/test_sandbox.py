import pytest

from more_core.sandbox.subprocess_sandbox import SubprocessSandbox


@pytest.mark.asyncio
async def test_run_python_captures_stdout() -> None:
    sbx = SubprocessSandbox(timeout_s=5)
    result = await sbx.run_python("print('ok')")
    assert result.exit_code == 0
    assert "ok" in result.stdout
    assert not result.timed_out


@pytest.mark.asyncio
async def test_timeout_kills_process() -> None:
    sbx = SubprocessSandbox(timeout_s=1)
    result = await sbx.run_python("import time; time.sleep(5)")
    assert result.timed_out is True
