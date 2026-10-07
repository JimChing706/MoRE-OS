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
    blocked_commands: list[str] = field(
        default_factory=lambda: [
            "rm",
            "dd",
            "mkfs",
            "shutdown",
            "reboot",
            "kill",
            "pkill",
            "sudo",
        ]
    )
    blocked_patterns: list[str] = field(
        default_factory=lambda: [
            r"\brm\s+-rf\b",
            r"\bpython3?\s+-c\s+",
            r"\bbash\s+-c\s+",
        ]
    )
    blocked_python_keywords: list[str] = field(
        default_factory=lambda: [
            "os.system",
            "subprocess.run",
            "subprocess.Popen",
            "shutil.rmtree",
            "os.remove",
            "pathlib.Path.unlink",
            "__import__('os')",
            "exec(",
            "eval(",
        ]
    )
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
            timestamp=time.time(),
            action=action,
            resource=resource,
            allowed=allowed,
            reason=reason,
            metadata=meta,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > self._config.audit_max_entries:
            self._audit_log = self._audit_log[-(self._config.audit_max_entries // 2) :]

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
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

    # -- policy checks -------------------------------------------------------

    def _check_command(self, full_cmd: str) -> tuple[bool, str]:
        """命令判定（R-10）：委托给策略层做**全 argv**检查。

        旧实现只取 ``full_cmd.split()[0]`` 比对黑名单，``sudo``、``env LD_PRELOAD=``、
        ``bash -c``、``python3 -c`` 等都能绕过；现在由
        :meth:`SandboxPolicy.check_command` 统一判定（含 shell 元字符、
        解释器内联代码、env 注入、全部 token 的命令名）。
        """
        if self._config.security_level == SecurityLevel.NONE:
            return True, ""
        if not (full_cmd or "").strip():
            return False, "empty command"
        try:
            from .policy import default_policy

            violations = default_policy().check_command(full_cmd)
        except Exception:  # pragma: no cover - 策略不可用时退回保守判定
            violations = []
        if violations:
            return False, "; ".join(violations)
        if self._config.security_level == SecurityLevel.STRICT:
            cmd_name = full_cmd.split()[0] if full_cmd.strip() else ""
            restricted = {"python", "python3", "node", "bash", "sh", "zsh"}
            if os.path.basename(cmd_name) in restricted and (
                self._process_count >= self._config.max_processes
            ):
                return False, f"max processes ({self._config.max_processes}) reached"
        return True, ""

    def _check_python_code(self, code: str) -> list[str]:
        """Static scan Python code for dangerous calls.

        Delegates to the unified :class:`SandboxPolicy` singleton; falls back
        to ``SandboxConfig.blocked_python_keywords`` when the policy is
        unavailable (e.g. during early bootstrap).
        """
        try:
            from .policy import default_policy

            policy = default_policy()
            violations = list(policy.scan_python(code))
            # STRICT：额外强制导入白名单（BASIC 不强制，避免误杀代码生成回路）
            if self._config.security_level == SecurityLevel.STRICT:
                disallowed = policy.validate_imports(code)
                if disallowed:
                    violations.append(f"disallowed imports: {', '.join(disallowed)}")
            return violations
        except Exception:
            pass
        # Legacy fallback for bootstrap ordering edge-cases
        violations: list[str] = []
        for kw in self._config.blocked_python_keywords:
            if kw in code:
                violations.append(f"blocked keyword: {kw}")
        return violations

    def _check_output(self, output: str) -> str:
        max_sz = self._config.max_output_size
        if len(output) > max_sz:
            _log.warning("output truncated from %d to %d bytes", len(output), max_sz)
            return output[:max_sz] + "\n... [output truncated]"
        return output

    def _check_path(self, path: str | None) -> tuple[bool, str]:
        """路径白名单校验（R-10）。

        旧实现用 ``resolved.startswith(realpath(ap))``，会把 ``/tmpfoo`` 误判为
        位于 ``/tmp`` 之下；且当调用方不传 ``cwd`` 时直接放行，使白名单形同虚设。
        现在：前缀按路径分段比较，并且 ``path=None`` 由调用方替换为默认沙箱目录。
        """
        if path is None:
            return False, "no cwd supplied (default sandbox dir required)"
        if not self._config.allow_filesystem:
            return False, "filesystem access denied"
        resolved = os.path.realpath(path)
        for ap in self._config.allowed_paths:
            root = os.path.realpath(ap)
            if resolved == root or resolved.startswith(root.rstrip(os.sep) + os.sep):
                return True, ""
        return False, f"path '{resolved}' not in allowed paths"

    def _default_cwd(self) -> str:
        """默认沙箱工作目录 —— **从白名单首个根派生**，保证自身就在白名单内。

        注意：不能用 ``tempfile.gettempdir()``，macOS 上它返回
        ``/var/folders/…``，不在默认 allowlist（``/tmp``）里，会被自己的路径检查拒绝。
        """
        roots = list(self._config.allowed_paths) or ["/tmp"]
        base = os.path.realpath(roots[0])
        root = os.path.join(base, "more_os_sbx")
        os.makedirs(root, exist_ok=True)
        return root

    @staticmethod
    def _sanitize_env(env: dict[str, str] | None) -> dict[str, str] | None:
        """剥离可劫持动态链接/解释器行为的危险环境变量。"""
        if env is None:
            return None
        blocked = {
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "LD_AUDIT",
            "DYLD_INSERT_LIBRARIES",
            "DYLD_LIBRARY_PATH",
            "PYTHONPATH",
            "PYTHONSTARTUP",
            "BASH_ENV",
            "ENV",
            "IFS",
        }
        return {k: v for k, v in env.items() if k not in blocked}

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
        # R-10：未显式指定 cwd 时落到默认沙箱目录，确保白名单始终生效
        cwd = cwd or self._default_cwd()
        env = self._sanitize_env(env)
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
        # Phase 1: static code analysis
        if self._config.security_level != SecurityLevel.NONE:
            violations = self._check_python_code(code)
            if violations:
                reason = "; ".join(violations)
                self._audit("run_python", "", False, reason)
                return SandboxResult(
                    stdout="",
                    stderr=f"Blocked: {reason}",
                    exit_code=-1,
                    duration_ms=0.0,
                )
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
    if isinstance(config, str) and security_level == "basic":
        # 容错：create_secure_sandbox("strict") 的位置参数会被当成 config，
        # 旧实现随后 AttributeError('str' has no 'timeout_s')——语义上应为安全级别。
        security_level, config = config, None
    if config is None:
        config = SandboxConfig(security_level=SecurityLevel(security_level), **kwargs)
    if inner is None:
        from .linux_sandbox import create_sandbox

        inner = create_sandbox(timeout_s=config.timeout_s, memory_mb=config.memory_mb)
    return SecureSandbox(inner, config)
