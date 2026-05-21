"""Enhanced Secure Sandbox with WASM-like isolation concepts."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SecurityLevel(Enum):
    """Security levels for sandbox."""
    NONE = "none"
    BASIC = "basic"
    STRICT = "strict"
    WASM_LIKE = "wasm_like"


@dataclass
class SandboxConfig:
    """Sandbox security configuration."""
    timeout_s: int = 30
    memory_mb: int = 256
    max_output_size: int = 1024 * 1024
    max_processes: int = 4
    allow_network: bool = False
    allow_filesystem: bool = True
    allowed_paths: list[str] = field(default_factory=list)
    blocked_commands: list[str] = field(default_factory=lambda: ["rm", "dd", "mkfs", "shutdown", "reboot", "kill", "pkill"])
    security_level: SecurityLevel = SecurityLevel.BASIC


@dataclass
class SecurityAudit:
    """Security audit trail entry."""
    timestamp: float
    action: str
    resource: str
    allowed: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SecureSandbox:
    """Enhanced sandbox with security controls and audit logging."""

    def __init__(self, config: SandboxConfig | None = None):
        self._config = config or SandboxConfig()
        self._audit_log: list[SecurityAudit] = []
        self._active_processes: dict[int, asyncio.Task] = {}
        self._process_count = 0

    @property
    def config(self) -> SandboxConfig:
        return self._config

    def _log_audit(self, action: str, resource: str, allowed: bool, reason: str, **metadata) -> None:
        """Log a security audit entry."""
        entry = SecurityAudit(
            timestamp=time.time(),
            action=action,
            resource=resource,
            allowed=allowed,
            reason=reason,
            metadata=metadata,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-500:]

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """Get recent audit log entries."""
        return [
            {
                "timestamp": e.timestamp,
                "action": e.action,
                "resource": e.resource,
                "allowed": e.allowed,
                "reason": e.reason,
            }
            for e in self._audit_log[-limit:]
        ]

    def check_command(self, cmd: str) -> tuple[bool, str]:
        """Check if a command is allowed."""
        cmd_name = cmd.split()[0] if cmd.split() else ""
        
        if self._config.security_level == SecurityLevel.NONE:
            return True, "allowed"
        
        for blocked in self._config.blocked_commands:
            if cmd_name == blocked or cmd_name.startswith(blocked):
                return False, f"command '{blocked}' is blocked"
        
        if self._config.security_level in (SecurityLevel.STRICT, SecurityLevel.WASM_LIKE):
            if cmd_name in ("python", "python3", "node", "bash", "sh", "zsh"):
                if self._process_count >= self._config.max_processes:
                    return False, "max processes reached"
        
        return True, "allowed"

    async def execute(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Execute a command with security checks."""
        full_cmd = f"{command} {' '.join(args)}" if args else command
        
        allowed, reason = self.check_command(full_cmd)
        if not allowed:
            self._log_audit("execute", full_cmd, False, reason)
            return {
                "success": False,
                "error": f"Security denied: {reason}",
                "audit": self.get_audit_log(1)[0] if self._audit_log else {},
            }
        
        self._log_audit("execute", full_cmd, True, "passed security checks")
        
        try:
            proc = await asyncio.create_subprocess_exec(
                command,
                *(args or []),
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            self._process_count += 1
            self._active_processes[proc.pid] = asyncio.create_task(proc.wait())
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._config.timeout_s,
                )
                output = stdout.decode("utf-8", "replace")
                if len(output) > self._config.max_output_size:
                    output = output[:self._config.max_output_size] + "\n... [output truncated]"
                
                result = {
                    "success": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "stdout": output,
                    "stderr": stderr.decode("utf-8", "replace"),
                    "duration_ms": 0,
                }
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                result = {
                    "success": False,
                    "error": "execution timeout",
                    "exit_code": -1,
                }
            finally:
                self._process_count = max(0, self._process_count - 1)
                self._active_processes.pop(proc.pid, None)
            
            return result
            
        except Exception as e:
            self._log_audit("execute", full_cmd, False, str(e))
            return {
                "success": False,
                "error": str(e),
            }

    def get_stats(self) -> dict[str, Any]:
        """Get sandbox statistics."""
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
    security_level: str = "basic",
    **kwargs,
) -> SecureSandbox:
    """Factory function to create a secure sandbox."""
    level = SecurityLevel(security_level)
    config = SandboxConfig(security_level=level, **kwargs)
    return SecureSandbox(config)