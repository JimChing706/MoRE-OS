"""Hardened Linux sandbox using cgroup v2 + unshare.

For production Linux deployments this replaces the baseline
``resource.setrlimit`` approach with proper kernel-level isolation:

- **PID namespace** via ``unshare --pid --fork``
- **Network isolation** via ``unshare --net``
- **Memory cap** via cgroup v2 ``memory.max``
- **CPU time cap** via cgroup v2 ``cpu.max``
- **Mount namespace** for filesystem isolation

Falls back to :class:`SubprocessSandbox` on non-Linux platforms.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from ..core.errors import SandboxError
from .subprocess_sandbox import SandboxResult, SubprocessSandbox

_log = logging.getLogger(__name__)


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def _cgroup_v2_available() -> bool:
    return Path("/sys/fs/cgroup/cgroup.controllers").exists()


class LinuxSandbox(SubprocessSandbox):
    """Hardened sandbox for Linux with cgroup v2 + unshare.

    On non-Linux or when cgroup v2 is unavailable, transparently
    falls back to the base :class:`SubprocessSandbox` behaviour.
    """

    def __init__(
        self,
        timeout_s: int = 20,
        memory_mb: int = 512,
        cpu_period_us: int = 100_000,
        cpu_quota_us: int = 50_000,
        enable_network: bool = False,
    ) -> None:
        super().__init__(timeout_s=timeout_s, memory_mb=memory_mb)
        self._cpu_period = cpu_period_us
        self._cpu_quota = cpu_quota_us
        self._enable_network = enable_network
        self._use_cgroup = is_linux() and _cgroup_v2_available()
        self._use_unshare = is_linux() and shutil.which("unshare") is not None
        self._cgroup_root = Path("/sys/fs/cgroup/more_sandbox")

    async def run(
        self,
        argv: list[str] | str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> SandboxResult:
        if not self._use_unshare:
            return await super().run(argv, cwd=cwd, env=env, stdin=stdin)

        import shlex

        if isinstance(argv, str):
            argv = shlex.split(argv)

        # Build the unshare wrapper command
        unshare_cmd = ["unshare", "--pid", "--fork", "--mount-proc"]
        if not self._enable_network:
            unshare_cmd.append("--net")

        cgroup_dir: Path | None = None
        if self._use_cgroup:
            cgroup_dir = await self._setup_cgroup()
            unshare_cmd.extend(["--cgroup", str(cgroup_dir)])

        full_cmd = unshare_cmd + ["--"] + argv
        start = asyncio.get_running_loop().time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                cwd=cwd,
                env=env or {"PATH": os.environ.get("PATH", "")},
                stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SandboxError(f"unshare or executable not found: {exc}") from exc

        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin else None),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                stdout="",
                stderr="sandbox timeout (linux hardened)",
                exit_code=-1,
                duration_ms=(asyncio.get_running_loop().time() - start) * 1000,
                timed_out=True,
            )
        finally:
            if cgroup_dir is not None:
                await self._teardown_cgroup(cgroup_dir)

        return SandboxResult(
            stdout=out.decode("utf-8", "replace"),
            stderr=err.decode("utf-8", "replace"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
            duration_ms=(asyncio.get_running_loop().time() - start) * 1000,
            timed_out=False,
        )

    # -- cgroup management -------------------------------------------------

    async def _setup_cgroup(self) -> Path:
        """Create an ephemeral cgroup v2 directory with resource limits."""
        import uuid

        cg_name = f"sbx_{uuid.uuid4().hex[:8]}"
        cg_dir = self._cgroup_root / cg_name
        try:
            cg_dir.mkdir(parents=True, exist_ok=True)
            # Memory limit
            (cg_dir / "memory.max").write_text(str(self._mem * 1024 * 1024))
            # CPU limit
            (cg_dir / "cpu.max").write_text(f"{self._cpu_quota} {self._cpu_period}")
            # PID limit
            (cg_dir / "pids.max").write_text("64")
        except OSError as exc:
            _log.warning("cgroup setup failed for %s: %s — falling back to no cgroup", cg_dir, exc)
        return cg_dir

    @staticmethod
    async def _teardown_cgroup(cg_dir: Path) -> None:
        """Remove the ephemeral cgroup directory."""
        try:
            # Kill any remaining processes
            procs_file = cg_dir / "cgroup.procs"
            if procs_file.exists():
                for pid in procs_file.read_text().strip().splitlines():
                    try:
                        os.kill(int(pid), 9)
                    except (ProcessLookupError, ValueError):
                        pass
            cg_dir.rmdir()
        except OSError:
            pass


def create_sandbox(
    timeout_s: int = 20,
    memory_mb: int = 512,
    **kwargs: Any,
) -> SubprocessSandbox:
    """Factory: returns :class:`LinuxSandbox` on Linux, else base sandbox."""
    if is_linux():
        return LinuxSandbox(timeout_s=timeout_s, memory_mb=memory_mb, **kwargs)
    return SubprocessSandbox(timeout_s=timeout_s, memory_mb=memory_mb)
