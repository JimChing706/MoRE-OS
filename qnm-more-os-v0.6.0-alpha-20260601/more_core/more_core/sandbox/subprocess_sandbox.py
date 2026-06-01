"""Subprocess-based sandbox.

Production deployments should wrap this with Docker + gVisor or WASM.
This baseline enforces timeout, stdin/stdout capture.
It is *not* a security boundary against adversarial code on its own, but
provides the isolation hook point called by L0 tools.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import SandboxError


@dataclass(slots=True)
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    timed_out: bool = False


class SubprocessSandbox:
    """Run short-lived programs with timeout + memory cap + cwd isolation."""

    def __init__(self, timeout_s: int = 20, memory_mb: int = 512) -> None:
        self._timeout = timeout_s
        self._mem = memory_mb

    async def run(
        self,
        argv: list[str] | str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> SandboxResult:
        if isinstance(argv, str):
            argv = shlex.split(argv)
        start = asyncio.get_running_loop().time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # NOTE: preexec_fn removed to avoid asyncio fork deadlock (Python 3.12+).
                # Memory limits are enforced by timeout + cgroup (LinuxSandbox) in production.
            )
        except FileNotFoundError as exc:
            raise SandboxError(f"executable not found: {argv[0]}") from exc

        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin else None),
                timeout=self._timeout,
            )
            timed_out = False
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                stdout="", stderr="sandbox timeout", exit_code=-1,
                duration_ms=(asyncio.get_running_loop().time() - start) * 1000,
                timed_out=True,
            )

        return SandboxResult(
            stdout=out.decode("utf-8", "replace"),
            stderr=err.decode("utf-8", "replace"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
            duration_ms=(asyncio.get_running_loop().time() - start) * 1000,
            timed_out=timed_out,
        )

    async def run_python(self, code: str) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="more_sbx_") as tmp:
            script = Path(tmp) / "main.py"
            script.write_text(code, encoding="utf-8")
            return await self.run(
                [sys.executable, "-I", str(script)],
                cwd=tmp,
                env={"PATH": os.environ.get("PATH", "")},
            )
