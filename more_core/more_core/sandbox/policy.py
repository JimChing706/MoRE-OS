"""Unified sandbox policy — single source of truth for code safety rules.

Shared by :class:`SecureSandbox` (L0 tool execution) and
:class:`SandboxValidator` (L5 HyperAgent validation).

R-10 加固说明
-------------
早期实现是**子串匹配**（``if "os.system" in code``），可以被平凡绕过：

    getattr(__import__("os"), "system")("...")
    import subprocess as s; s.run([...])
    from os import system; system("...")

现在 ``scan_python`` 改为**基于 AST** 的判定：
  * 解析失败一律拦截（避免"分析器看不懂 = 放行"）；
  * 解析 ``Call`` 节点的被调对象 dotted name，并跟踪 ``import ... as`` /
    ``from ... import ...`` 建立的别名；
  * 对高风险模块的导入本身也拦截（subprocess / ctypes / socket / importlib …）；
  * 保留 ``blocked_python_keywords`` 作为**额外**信号（兼容旧调用方与测试）。

注意：``scan_python`` 只判"危险操作"，不做导入白名单；
导入白名单仍由 ``validate_imports`` 提供给更严格的 L5 验证路径，
以免把 L0 代码生成回路里正常的 ``import statistics`` 之类误杀。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

__all__ = ["SandboxPolicy", "default_policy", "reset_default_policy"]


#: 高风险调用（被调对象解析后的 dotted name）。
_DANGEROUS_CALLS: frozenset[str] = frozenset(
    {
        # 进程 / shell
        "os.system", "os.popen", "os.execv", "os.execve", "os.execl", "os.execlp",
        "os.execvp", "os.execvpe", "os.spawnl", "os.spawnv", "os.spawnlp", "os.fork",
        "os.forkpty", "os.kill", "os.killpg", "os.setuid", "os.setgid",
        "subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_call",
        "subprocess.check_output", "subprocess.getoutput", "subprocess.getstatusoutput",
        # 文件系统破坏
        "shutil.rmtree", "shutil.move", "shutil.copytree",
        "os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.chmod", "os.chown",
        "pathlib.Path.unlink", "pathlib.Path.rmdir", "pathlib.Path.chmod",
        "pathlib.Path.write_text", "pathlib.Path.write_bytes",
        # 动态执行 / 反射式导入
        "eval", "exec", "compile", "__import__",
        "builtins.eval", "builtins.exec", "builtins.__import__",
        "importlib.import_module", "importlib.__import__", "importlib.reload",
        # 网络 / 原生互操作 / 反序列化
        "socket.socket", "socket.create_connection", "socket.create_server",
        "ctypes.CDLL", "ctypes.PyDLL", "ctypes.cdll.LoadLibrary",
        "ctypes.windll", "ctypes.util.find_library",
        "pickle.loads", "pickle.Unpickler", "marshal.loads", "shelve.open",
        "urllib.request.urlopen", "http.client.HTTPConnection",
        # 运行时自省 / 调试钩子
        "sys.settrace", "sys.setprofile", "sys._getframe",
        "resource.setrlimit", "signal.signal",
    }
)

#: 这些模块一旦被导入即视为高风险（无论是否真的调用了危险函数）。
_DANGEROUS_MODULE_ROOTS: frozenset[str] = frozenset(
    {"subprocess", "ctypes", "socket", "importlib", "pty", "pickle", "marshal"}
)

#: 允许写入的前缀（Path 前缀匹配，杜绝 /tmpfoo 这类误判）。
_DEFAULT_WRITABLE_ROOTS: tuple[str, ...] = ("/tmp", "/private/tmp", "/var/folders")


def _dotted(node: ast.AST, aliases: dict[str, str] | None = None) -> str:
    """把 ``a.b.c`` 形式的属性访问还原成点号字符串（无法还原时返回 ""）。"""
    parts: list[str] = []
    cur: ast.AST | None = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        root = (aliases or {}).get(cur.id, cur.id)
        parts.append(root)
        return ".".join(reversed(parts))
    return ""


@dataclass
class SandboxPolicy:
    """Immutable policy object for sandbox code safety."""

    # 兼容字段：作为 AST 判定之外的**额外**信号保留
    blocked_python_keywords: list[str] = field(
        default_factory=lambda: [
            "os.system",
            "subprocess.run",
            "subprocess.Popen",
            "shutil.rmtree",
            "os.remove",
            "pathlib.Path.unlink",
            "exec(",
            "eval(",
        ]
    )

    # Imports allowed during sandbox execution (HyperAgent-style validation).
    allowed_imports: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "math", "random", "re", "json", "datetime", "time", "collections",
                "itertools", "functools", "typing", "dataclasses", "enum", "pathlib",
                "os.path", "textwrap", "hashlib", "base64", "uuid", "copy", "pprint",
                "statistics", "decimal", "fractions",
            }
        )
    )

    # Patterns that indicate dangerous shell / filesystem operations.
    blocked_shell_patterns: list[str] = field(
        default_factory=lambda: [
            r"\brm\s+-rf\b",
            r"\bpython3?\s+-c\s+",
            r"\bbash\s+-c\s+",
            r"\bsh\s+-c\s+",
            r"\$\(",              # 命令替换
            r"`[^`]+`",           # 反引号命令替换
            r"\|\s*(?:sh|bash)\b",  # curl … | sh
            r">\s*/dev/",         # 写设备
        ]
    )

    # System commands denied at the sandbox boundary.
    blocked_commands: list[str] = field(
        default_factory=lambda: [
            "rm", "dd", "mkfs", "shutdown", "reboot", "kill", "pkill", "sudo",
            "chown", "chmod", "mount", "umount", "nc", "netcat", "ncat",
        ]
    )

    # 解释器 + 内联代码/危险开关
    dangerous_interpreter_flags: frozenset[str] = frozenset(
        {"-c", "-e", "--eval", "-E", "--exec", "-x"}
    )
    interpreters: frozenset[str] = frozenset(
        {"python", "python3", "node", "ruby", "perl", "php", "bash", "sh", "zsh", "ksh", "osascript"}
    )

    #: 允许写入的路径前缀（用于 open(..., "w") 的静态判定）
    writable_roots: tuple[str, ...] = _DEFAULT_WRITABLE_ROOTS

    # ------------------------------------------------------------------
    # Python 源码
    # ------------------------------------------------------------------

    def scan_python(self, code: str) -> list[str]:
        """AST 判定 Python 源码是否包含危险操作。返回违规描述列表（空 = 通过）。"""
        violations: list[str] = []
        if not code or not code.strip():
            return ["blocked keyword: empty code"]

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            # 解析不了就拦 —— 不能让"分析器看不懂"变成放行理由
            return [f"blocked: cannot parse python source ({exc.msg} @ line {exc.lineno})"]

        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    bound = alias.asname or root
                    aliases[bound] = alias.name
                    if root in _DANGEROUS_MODULE_ROOTS:
                        violations.append(f"blocked import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".")[0]
                if root in _DANGEROUS_MODULE_ROOTS:
                    violations.append(f"blocked import: from {module}")
                for alias in node.names:
                    bound = alias.asname or alias.name
                    aliases[bound] = f"{module}.{alias.name}" if module else alias.name

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _dotted(node.func, aliases)
                if not name:
                    continue
                # 别名解析后仍可能是裸函数名（from os import system）
                if name in _DANGEROUS_CALLS:
                    violations.append(f"blocked call: {name}()")
                    continue
                # os.path.* 白名单：允许 join/abspath 等纯路径运算
                if name.startswith("os.path."):
                    continue
                simple = name.rsplit(".", 1)[-1]
                if name.split(".")[0] in {"os", "shutil"} and simple in {
                    "system", "popen", "remove", "unlink", "rmdir", "rmtree",
                }:
                    violations.append(f"blocked call: {name}()")
            elif isinstance(node, ast.Attribute):
                # 即使没被调用，取 os.system 这类属性也视为可疑
                name = _dotted(node, aliases)
                if name in _DANGEROUS_CALLS:
                    violations.append(f"blocked attribute: {name}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
                for kw in self.blocked_python_keywords:
                    if kw in text and ("import" in text or "system" in text):
                        violations.append(f"blocked keyword in string: {kw}")

        return list(dict.fromkeys(violations))

    def validate_imports(self, code: str) -> list[str]:
        """AST 版导入白名单校验（比按行前缀匹配严格得多）。"""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return [f"<syntax-error:{exc.msg}>"]
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not self._module_allowed(alias.name):
                        violations.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module and not self._module_allowed(module):
                    violations.append(module)
        return list(dict.fromkeys(v for v in violations if v))

    def _module_allowed(self, module: str) -> bool:
        """模块是否在白名单内（精确匹配或**其子模块**）。

        刻意不做 root 匹配：白名单里有 ``os.path`` 不代表允许 ``import os``
        —— 后者会把整个 os 模块（含 os.system）带进来。
        """
        if module in self.allowed_imports:
            return True
        return any(module.startswith(allowed + ".") for allowed in self.allowed_imports)

    def is_safe(self, code: str) -> tuple[bool, str]:
        """Convenience: run both scans and return (safe, reason)."""
        kw_violations = self.scan_python(code)
        if kw_violations:
            return False, "; ".join(kw_violations)
        import_violations = self.validate_imports(code)
        if import_violations:
            return False, f"disallowed imports: {', '.join(import_violations)}"
        return True, ""

    # ------------------------------------------------------------------
    # 命令行
    # ------------------------------------------------------------------

    def check_command(self, argv: list[str] | str) -> list[str]:
        """对**完整 argv** 做判定（旧实现只看第一个 token）。"""
        import re as _re
        import shlex

        if isinstance(argv, str):
            raw = argv
            try:
                tokens = shlex.split(argv)
            except ValueError:
                return ["blocked: unbalanced quotes in command"]
            for pattern in self.blocked_shell_patterns:
                if _re.search(pattern, raw):
                    return [f"blocked pattern: {pattern}"]
        else:
            raw = " ".join(argv)
            tokens = list(argv)

        if not tokens:
            return ["blocked: empty command"]

        violations: list[str] = []
        for tok in tokens:
            base = tok.rsplit("/", 1)[-1]
            if base in self.blocked_commands:
                violations.append(f"blocked command: {base}")
        # 解释器 + 内联代码
        exe = tokens[0].rsplit("/", 1)[-1]
        if exe in self.interpreters and any(t in self.dangerous_interpreter_flags for t in tokens[1:]):
            violations.append(f"blocked inline code execution: {exe} {' '.join(tokens[1:3])}")
        # env VAR=VALUE 注入（LD_PRELOAD / DYLD_* / PYTHONPATH …）
        if exe == "env":
            for tok in tokens[1:]:
                if "=" in tok:
                    key = tok.split("=", 1)[0]
                    if key in {"LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
                               "DYLD_LIBRARY_PATH", "PYTHONPATH", "PYTHONSTARTUP"}:
                        violations.append(f"blocked env injection: {key}")

        # 路径穿越 / 敏感路径读取（R-10）
        # 仅校验 cwd 是不够的：命令参数里的 ``../../../etc/passwd`` 依然能逃出沙箱根。
        for tok in tokens[1:]:
            norm = tok.replace("\\", "/")
            segments = [seg for seg in norm.split("/") if seg not in ("", ".")]
            if any(seg == ".." for seg in segments):
                violations.append(f"blocked path traversal: {tok}")
                continue
            for sensitive in ("/etc/passwd", "/etc/shadow", "/etc/sudoers",
                              "/root/", "/.ssh/", "/var/root/"):
                if norm == sensitive.rstrip("/") or sensitive in norm:
                    violations.append(f"blocked sensitive path: {tok}")
                    break
        return violations


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
