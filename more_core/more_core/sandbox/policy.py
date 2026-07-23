"""Unified sandbox policy — single source of truth for code safety rules.

Shared by :class:`SecureSandbox` (L0 tool execution) and
:class:`SandboxValidator` (L5 HyperAgent validation).

Usage::

    from more_core.sandbox.policy import SandboxPolicy, default_policy
    policy = default_policy()
    violations = policy.scan_python(code)
    allowed_imports = policy.allowed_imports
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SandboxPolicy:
    """Immutable policy object for sandbox code safety."""

    # Python keywords / patterns that are unconditionally blocked.
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

    # Imports allowed during sandbox execution (HyperAgent-style validation).
    allowed_imports: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "math",
                "random",
                "re",
                "json",
                "datetime",
                "time",
                "collections",
                "itertools",
                "functools",
                "typing",
                "dataclasses",
                "enum",
                "pathlib",
                "os.path",
                "textwrap",
                "hashlib",
                "base64",
                "uuid",
                "copy",
                "pprint",
                "statistics",
                "decimal",
                "fractions",
            }
        )
    )

    # Patterns that indicate dangerous shell / filesystem operations.
    blocked_shell_patterns: list[str] = field(
        default_factory=lambda: [
            r"\brm\s+-rf\b",
            r"\bpython3?\s+-c\s+",
            r"\bbash\s+-c\s+",
        ]
    )

    # System commands denied at the sandbox boundary.
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

    def scan_python(self, code: str) -> list[str]:
        """Static scan of Python *code* for dangerous patterns.

        Returns a list of violation descriptions (empty = clean).
        """
        violations: list[str] = []
        for kw in self.blocked_python_keywords:
            if kw in code:
                violations.append(f"blocked keyword: {kw}")
        return violations

    def validate_imports(self, code: str) -> list[str]:
        """Check that all imports in *code* are in the allowed set.

        Returns a list of disallowed module names (empty = clean).
        """
        violations: list[str] = []
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("import "):
                module = stripped.split()[1].split(" as ")[0].strip()
                if module not in self.allowed_imports:
                    violations.append(module)
            elif stripped.startswith("from "):
                parts = stripped.split()
                module = parts[1]
                if module not in self.allowed_imports:
                    violations.append(module)
        return violations

    def is_safe(self, code: str) -> tuple[bool, str]:
        """Convenience: run both scans and return (safe, reason)."""
        kw_violations = self.scan_python(code)
        if kw_violations:
            return False, "; ".join(kw_violations)
        import_violations = self.validate_imports(code)
        if import_violations:
            return False, f"disallowed imports: {', '.join(import_violations)}"
        return True, ""


# Singleton default policy instance — import this everywhere.
_default: SandboxPolicy | None = None


def default_policy() -> SandboxPolicy:
    """Return the global default :class:`SandboxPolicy` (lazy singleton)."""
    global _default
    if _default is None:
        _default = SandboxPolicy()
    return _default


def reset_default_policy() -> None:
    """Reset the global policy (useful for tests)."""
    global _default
    _default = None
