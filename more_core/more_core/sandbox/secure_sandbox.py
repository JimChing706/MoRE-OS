"""Secure sandbox wrapper — adds policy checks and audit logging.

Wraps a :class:`SubprocessSandbox` (or :class:`LinuxSandbox`) with:

* Command whitelist / blacklist checks
* Process count limits
* Output size limits
* Security audit trail

Usage::

    inner = SubprocessSandbox(timeout_s=30, memory_mb=256)
    sandbox = SecureSandbox(inner, security_level="strict")
    result = await sandbox.run(["python3", "script.py"])
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .subprocess_sandbox import SandboxResult, SubprocessSandbox

_log = logging.getLogger(__name__)


class SecurityLevel(Enum):
    NONE = "none"
    BASIC = "basic"
    STRICT = "strict"


@dataclass
class SandboxConfig:
    timeout_s: int = 30
    memory_mb: int = 256
    max_output_size: int = 1_048_576
    max_processes: int = 4
    allow_network: bool = False
    allow_filesystem: bool = True
    allowed_paths: list[str] = field(default_factory=lambda: ["/tmp"])
    blocked_commands: list[str] = field(default_factory=lambda: [
        "rm", "dd", "mkfs", "shutdown", "reboot", "kill", "pkill", "sudo",
    ])
    security_level: SecurityLevel = SecurityLevel.BASIC
    audit_enabled: bool = True
    audit_max_entries: int = 1000


@dataclass
class AuditEntry:
    timestamp: float
    action: str
    resource: str
    allowed: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SecureSandbox:
    """Policy-enforcing wrapper around a base sandbox."""

    def __init__(
        self,
        inner: SubprocessSandbox,
        config: SandboxConfig | None = None,
    ) -> None:
        self._inner = inner
        self._config = config or SandboxConfig()
        self._audit_log: list[AuditEntry] = []
        self._process_count = 0

    @property
    def config(self) -> SandboxConfig:
        return self._config

    def _audit(self, action: str, resource: str, allowed: bool, reason: str, **meta: Any) -> None:
        if not self._config.audit_enabled:
            return
        entry = AuditEntry(
            timestamp=time.time(), action=action, resource=resource,
            allowed=allowed, reason=reason, metadata=meta,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > self._config.audit_max_entries:
            self._audit_log = self._audit_log[-(self._config.audit_max_entries // 2):]

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {"timestamp": e.timestamp, "action": e.action, "resource": e.resource,
             "allowed": e.allowed, "reason": e.reason}
            for e in self._audit_log[-limit:]
        ]

    # -- policy checks -------------------------------------------------------

    def _check_command(self, full_cmd: str) -> tuple[bool, str]:
        if self._config.security_level == SecurityLevel.NONE:
            return True, ""
        cmd_name = full_cmd.split()[0] if full_cmd.strip() else ""
        if not cmd_name:
            return False, "empty command"
        cmd_base = os.path.basename(cmd_name) or cmd_name
        for blocked in self._config.blocked_commands:
            if cmd_name == blocked or cmd_base == blocked:
                return False, f"command '{blocked}' is blocked"
        if self._config.security_level == SecurityLevel.STRICT:
            restricted = {"python", "python3", "node", "bash", "sh", "zsh"}
            if cmd_name in restricted and self._process_count >= self._config.max_processes:
                return False, f"max processes ({self._config.max_processes}) reached"
        return True, ""

    def _check_output(self, output: str) -> str:
        max_sz = self._config.max_output_size
        if len(output) > max_sz:
            _log.warning("output truncated from %d to %d bytes", len(output), max_sz)
            return output[:max_sz] + "\n... [output truncated]"
        return output

    def _check_path(self, path: str | None) -> tuple[bool, str]:
        if path is None:
            return True, ""
        if not self._config.allow_filesystem:
            return False, "filesystem access denied"
        resolved = os.path.realpath(path)
        allowed = False
        for ap in self._config.allowed_paths:
            if resolved.startswith(os.path.realpath(ap)):
                allowed = True
                break
        if not allowed:
            return False, f"path '{resolved}' not in allowed paths"
        return True, ""

    # -- public API (same interface as SubprocessSandbox) --------------------

    async def run(
        self,
        argv: list[str] | str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> SandboxResult:
        cmd_str = argv if isinstance(argv, str) else " ".join(argv)
        allowed, reason = self._check_command(cmd_str)
        if not allowed:
            self._audit("run", cmd_str, False, reason)
            return SandboxResult(stdout="", stderr=reason, exit_code=-1, duration_ms=0.0)
        path_allowed, path_reason = self._check_path(cwd)
        if not path_allowed:
            self._audit("run", cmd_str, False, path_reason, cwd=cwd)
            return SandboxResult(stdout="", stderr=path_reason, exit_code=-1, duration_ms=0.0)

        self._process_count += 1
        self._audit("run", cmd_str, True, "passed policy checks")
        try:
            result = await self._inner.run(argv, cwd=cwd, env=env, stdin=stdin)
            result.stdout = self._check_output(result.stdout)
            return result
        finally:
            self._process_count = max(0, self._process_count - 1)

    async def run_python(self, code: str) -> SandboxResult:
        allowed, reason = self._check_command("python3")
        if not allowed:
            self._audit("run_python", "", False, reason)
            return SandboxResult(stdout="", stderr=reason, exit_code=-1, duration_ms=0.0)

        self._process_count += 1
        self._audit("run_python", "", True, "passed policy checks")
        try:
            result = await self._inner.run_python(code)
            result.stdout = self._check_output(result.stdout)
            return result
        finally:
            self._process_count = max(0, self._process_count - 1)

    # -- stats ---------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        return {
            "security_level": self._config.security_level.value,
            "active_processes": self._process_count,
            "max_processes": self._config.max_processes,
            "timeout_s": self._config.timeout_s,
            "memory_mb": self._config.memory_mb,
            "audit_entries": len(self._audit_log),
            "allow_network": self._config.allow_network,
        }


def create_secure_sandbox(
    config: SandboxConfig | None = None,
    *,
    inner: SubprocessSandbox | None = None,
    security_level: str = "basic",
    **kwargs: Any,
) -> SecureSandbox:
    """Unified factory: creates the full sandbox stack.

    If *config* is given it is used directly; otherwise one is built from
    *security_level* + *kwargs*.  If *inner* is not supplied, the best
    platform sandbox is auto-created via :func:`create_sandbox`.

    This is the **primary public API** for sandbox creation.
    """
    if config is None:
        config = SandboxConfig(security_level=SecurityLevel(security_level), **kwargs)
    if inner is None:
        from .linux_sandbox import create_sandbox
        inner = create_sandbox(timeout_s=config.timeout_s, memory_mb=config.memory_mb)
    return SecureSandbox(inner, config)
