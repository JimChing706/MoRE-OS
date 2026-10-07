"""Built-in tools shipped with MoRE Core.

These are *platform-neutral* capabilities.  Industry-specific tools
(e.g. database query, API gateway, domain search) must be added via plugins.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..security.rbac import Permission
from .registry import ToolDefinition, ToolRegistry, ToolResult

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime.orchestrator import MoRECore


async def _python_exec(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    code = params.get("code", "")
    if not code.strip():
        return ToolResult(tool="python_exec", success=False, error="empty code")
    sbx = await core.sandbox.run_python(code)
    return ToolResult(
        tool="python_exec",
        success=sbx.exit_code == 0 and not sbx.timed_out,
        output=sbx.stdout.strip() or sbx.stderr.strip(),
        error=sbx.stderr.strip() if sbx.exit_code != 0 else "",
    )


async def _shell_exec(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    command = params.get("command", "")
    if not command.strip():
        return ToolResult(tool="shell_exec", success=False, error="empty command")
    sbx = await core.sandbox.run(command)
    return ToolResult(
        tool="shell_exec",
        success=sbx.exit_code == 0 and not sbx.timed_out,
        output=sbx.stdout.strip(),
        error=sbx.stderr.strip() if sbx.exit_code != 0 else "",
    )


async def _memory_search(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    query = params.get("query", "")
    kind_str = params.get("kind")
    from ..memory.store import MemoryKind

    kind = MemoryKind(kind_str) if kind_str else None
    results = core.memory.search(query, kind=kind, top_k=params.get("top_k", 5))
    return ToolResult(
        tool="memory_search",
        success=True,
        output=[{"id": e.id, "content": e.content, "score": e.score} for e in results],
    )


async def _memory_store(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    from ..memory.store import MemoryEntry, MemoryKind

    entry = MemoryEntry(
        content=params.get("content", ""),
        kind=MemoryKind(params.get("kind", "episodic")),
        tags=params.get("tags", []),
    )
    core.memory.put(entry)
    return ToolResult(tool="memory_store", success=True, output={"id": entry.id})


async def _grep_files(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Grep-like search with line numbers and context."""
    root = await _project_root(core)
    query = params.get("query", "")
    file_pattern = params.get("file_pattern", "**/*.py")
    regex = params.get("regex", False)

    if not query:
        return ToolResult(tool="grep_files", success=False, error="empty query")

    pattern = re.compile(query) if regex else re.compile(re.escape(query))
    matches = []

    for path in root.glob(file_pattern):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    matches.append(
                        {
                            "file": str(path.relative_to(root)),
                            "line": i,
                            "content": line.strip()[:200],
                        }
                    )
                    if len(matches) >= 50:
                        break
        except Exception:  # noqa: BLE001, S112
            continue
        if len(matches) >= 50:
            break

    return ToolResult(
        tool="grep_files",
        success=True,
        output={"matches": matches[:50], "total": len(matches)},
    )


async def _file_info(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Get file metadata (size, modified, permissions)."""
    root = await _project_root(core)
    path = params.get("path", "")

    if not path:
        return ToolResult(tool="file_info", success=False, error="empty path")

    full_path = (root / path).resolve()
    try:
        full_path.relative_to(root)
    except ValueError:
        return ToolResult(
            tool="file_info", success=False, error="access denied: path is outside project root"
        )
    if not full_path.exists():
        return ToolResult(tool="file_info", success=False, error="file not found")

    stat = full_path.stat()
    return ToolResult(
        tool="file_info",
        success=True,
        output={
            "path": path,
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
            "is_file": full_path.is_file(),
            "is_dir": full_path.is_dir(),
        },
    )


async def _create_directory(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Create a new directory."""
    root = await _project_root(core)
    path = params.get("path", "")

    if not path:
        return ToolResult(tool="create_directory", success=False, error="empty path")

    full_path = (root / path).resolve()
    try:
        full_path.relative_to(root)
    except ValueError:
        return ToolResult(
            tool="create_directory",
            success=False,
            error="access denied: path is outside project root",
        )
    try:
        full_path.mkdir(parents=True, exist_ok=True)
        return ToolResult(tool="create_directory", success=True, output={"path": path})
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="create_directory", success=False, error=str(e))


async def _delete_file(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Delete a file or directory."""
    root = await _project_root(core)
    path = params.get("path", "")
    recursive = params.get("recursive", False)

    if not path:
        return ToolResult(tool="delete_file", success=False, error="empty path")

    full_path = (root / path).resolve()
    try:
        full_path.relative_to(root)
    except ValueError:
        return ToolResult(
            tool="delete_file", success=False, error="access denied: path is outside project root"
        )
    if not full_path.exists():
        return ToolResult(tool="delete_file", success=False, error="path does not exist")

    try:
        if full_path.is_dir():
            if recursive:
                import shutil

                shutil.rmtree(full_path)
            else:
                full_path.rmdir()
        else:
            full_path.unlink()
        return ToolResult(tool="delete_file", success=True, output={"path": path})
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="delete_file", success=False, error=str(e))


async def _project_root(core: MoRECore) -> Path:
    """Get the current project root from core context, or fall back to cwd."""
    if hasattr(core, "project_root") and core.project_root:
        return Path(core.project_root).resolve()
    return Path.cwd().resolve()


async def _read_file(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Read the contents of a file."""
    file_path = params.get("path", "")
    if not file_path:
        return ToolResult(tool="read_file", success=False, error="path parameter is required")

    root = await _project_root(core)
    try:
        target = (root / file_path).resolve()
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="read_file", success=False, error=f"invalid path: {e}")

    try:
        target.relative_to(root)
    except ValueError:
        return ToolResult(
            tool="read_file",
            success=False,
            error=f"access denied: {file_path} is outside project root",
        )

    if not target.exists():
        return ToolResult(tool="read_file", success=False, error=f"file not found: {file_path}")

    if not target.is_file():
        return ToolResult(tool="read_file", success=False, error=f"not a file: {file_path}")

    try:
        content = target.read_text(encoding="utf-8")
        return ToolResult(tool="read_file", success=True, output=content)
    except UnicodeDecodeError:
        try:
            content = target.read_bytes().decode("utf-8", errors="replace")
            return ToolResult(tool="read_file", success=True, output=content)
        except Exception as e:  # noqa: BLE001
            return ToolResult(tool="read_file", success=False, error=f"cannot read file: {e}")
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="read_file", success=False, error=f"read error: {e}")


async def _write_file(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Write contents to a file."""
    file_path = params.get("path", "")
    content = params.get("content", "")

    if not file_path:
        return ToolResult(tool="write_file", success=False, error="path parameter is required")
    if content is None:
        return ToolResult(tool="write_file", success=False, error="content parameter is required")

    root = await _project_root(core)
    try:
        target = (root / file_path).resolve()
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="write_file", success=False, error=f"invalid path: {e}")

    try:
        target.relative_to(root)
    except ValueError:
        return ToolResult(tool="write_file", success=False, error="access denied")

    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(content, encoding="utf-8")
        return ToolResult(
            tool="write_file", success=True, output=f"wrote {len(content)} chars to {file_path}"
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="write_file", success=False, error=f"write error: {e}")


async def _list_directory(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """List files in a directory."""
    dir_path = params.get("path", "")
    recursive = params.get("recursive", False)

    root = await _project_root(core)

    if not dir_path:
        target = root
    else:
        try:
            target = (root / dir_path).resolve()
        except Exception as e:  # noqa: BLE001
            return ToolResult(tool="list_directory", success=False, error=f"invalid path: {e}")

        try:
            target.relative_to(root)
        except ValueError:
            return ToolResult(tool="list_directory", success=False, error="access denied")

    if not target.exists():
        return ToolResult(tool="list_directory", success=False, error="directory not found")

    if not target.is_dir():
        return ToolResult(tool="list_directory", success=False, error="not a directory")

    try:
        entries = []
        if recursive:
            for p in sorted(target.rglob("*")):
                if ".git" in p.parts or "node_modules" in p.parts or "__pycache__" in p.parts:
                    continue
                rel = p.relative_to(root)
                entries.append(
                    {
                        "path": str(rel),
                        "type": "directory" if p.is_dir() else "file",
                        "size": p.stat().st_size if p.is_file() else None,
                    }
                )
        else:
            for p in sorted(target.iterdir()):
                if p.name.startswith("."):
                    continue
                rel = p.relative_to(root)
                entries.append(
                    {
                        "path": str(rel),
                        "type": "directory" if p.is_dir() else "file",
                        "size": p.stat().st_size if p.is_file() else None,
                    }
                )
        return ToolResult(tool="list_directory", success=True, output=json.dumps(entries, indent=2))
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="list_directory", success=False, error=f"list error: {e}")


async def _search_code(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Search for text or regex patterns in code files."""
    query = params.get("query", "")
    file_pattern = params.get("file_pattern", "**/*")
    use_regex = params.get("regex", False)

    if not query:
        return ToolResult(tool="search_code", success=False, error="query parameter is required")

    root = await _project_root(core)

    try:
        if use_regex:
            pattern = re.compile(query, re.MULTILINE)
        else:
            pattern = None
    except re.error as e:
        return ToolResult(tool="search_code", success=False, error=f"invalid regex: {e}")

    matches = []
    try:
        for file_path in root.glob("**/*"):
            if any(part.startswith(".") for part in file_path.parts):
                continue
            if not file_path.is_file():
                continue

            rel_path = file_path.relative_to(root)

            # PurePath.match("**/*.py") may not match top-level files;
            # also try matching just the filename against the suffix pattern.
            if not (
                rel_path.match(file_pattern)
                or (file_pattern.startswith("**/") and rel_path.match(file_pattern[3:]))
            ):
                continue

            skip_dirs = {
                ".git",
                "node_modules",
                "__pycache__",
                ".ruff_cache",
                ".pytest_cache",
                "venv",
            }
            if any(skip in rel_path.parts for skip in skip_dirs):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.split("\n")

                for line_num, line in enumerate(lines, 1):
                    if use_regex:
                        assert pattern is not None
                        if pattern.search(line):
                            matches.append(
                                {
                                    "file": str(rel_path),
                                    "line": line_num,
                                    "text": line.strip(),
                                }
                            )
                    else:
                        if query in line:
                            matches.append(
                                {
                                    "file": str(rel_path),
                                    "line": line_num,
                                    "text": line.strip(),
                                }
                            )
            except (UnicodeDecodeError, OSError):
                continue

            if len(matches) > 500:
                break
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="search_code", success=False, error=f"search error: {e}")

    output = {
        "total_matches": len(matches),
        "truncated": len(matches) >= 500,
        "matches": matches[:500],
    }
    return ToolResult(tool="search_code", success=True, output=json.dumps(output, indent=2))


async def _run_tests(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Run pytest tests."""
    test_path = params.get("path", ".")
    pattern = params.get("pattern", "test_*.py")
    verbose = params.get("verbose", False)

    root = await _project_root(core)
    test_dir = (root / test_path).resolve()

    try:
        test_dir.relative_to(root)
    except ValueError:
        return ToolResult(tool="run_tests", success=False, error="path outside project root")

    if not test_dir.exists():
        return ToolResult(tool="run_tests", success=False, error="path not found")

    cmd_parts = ["pytest", shlex.quote(str(test_path)), "-p", "no:cacheprovider"]
    if not verbose:
        cmd_parts.extend(["-q", "--tb=short"])
    cmd_parts.extend(["--tb=short", "-k", shlex.quote(pattern)])
    cmd = " ".join(cmd_parts)

    try:
        sbx = await core.sandbox.run(cmd, timeout=300)
        success = sbx.exit_code == 0 and not sbx.timed_out
        output = sbx.stdout.strip() or sbx.stderr.strip()
        error = sbx.stderr.strip() if sbx.exit_code != 0 else ""

        return ToolResult(
            tool="run_tests",
            success=success,
            output=output[:2000] if output else "no output",
            error=error[:2000] if error else "",
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="run_tests", success=False, error=f"test execution error: {e}")


async def _lint_file(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Lint a Python file."""
    file_path = params.get("path", "")

    if not file_path:
        return ToolResult(tool="lint_file", success=False, error="path parameter is required")

    root = await _project_root(core)
    try:
        target = (root / file_path).resolve()
        target.relative_to(root)
    except Exception:  # noqa: BLE001
        return ToolResult(tool="lint_file", success=False, error="invalid path")

    if not target.exists() or not target.is_file():
        return ToolResult(tool="lint_file", success=False, error="file not found")

    try:
        sbx = await core.sandbox.run(f"pycodestyle --max-line-length=100 {shlex.quote(file_path)}")
        output = sbx.stdout.strip() or sbx.stderr.strip()

        if sbx.exit_code != 0:
            try:
                sbx2 = await core.sandbox.run(f"python -m py_compile {shlex.quote(file_path)}")
                if sbx2.exit_code == 0:
                    output = "Syntax OK"
            except Exception:  # noqa: BLE001, S110
                pass

        return ToolResult(
            tool="lint_file",
            success=sbx.exit_code == 0 and not sbx.timed_out,
            output=output[:3000] if output else "No issues found",
            error="",
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="lint_file", success=False, error=f"lint error: {e}")


async def _format_code(params: dict[str, Any], *, core: MoRECore) -> ToolResult:
    """Format Python code with black."""
    file_path = params.get("path", "")
    check_only = params.get("check", False)

    if not file_path:
        return ToolResult(tool="format_code", success=False, error="path parameter is required")

    root = await _project_root(core)
    try:
        target = (root / file_path).resolve()
        target.relative_to(root)
    except Exception:  # noqa: BLE001
        return ToolResult(tool="format_code", success=False, error="invalid path")

    if not target.exists() or not target.is_file():
        return ToolResult(tool="format_code", success=False, error="file not found")

    try:
        cmd = f"black {'--check --diff' if check_only else ''} {shlex.quote(file_path)}"
        sbx = await core.sandbox.run(cmd, timeout=60)
        output = sbx.stdout.strip() or sbx.stderr.strip()

        if sbx.exit_code in (0, 1):
            msg = (
                "Already formatted"
                if check_only and sbx.exit_code == 0
                else "Formatted with changes"
                if sbx.exit_code == 1
                else "Formatted successfully"
            )
            return ToolResult(tool="format_code", success=True, output=msg)
        else:
            return ToolResult(tool="format_code", success=False, error=f"formatter error: {output}")
    except Exception as e:  # noqa: BLE001
        return ToolResult(tool="format_code", success=False, error=f"format error: {e}")


def register_builtins(registry: ToolRegistry, core: MoRECore) -> None:
    """Register platform-level tools.  Called during :meth:`MoRECore.start`."""

    registry.register(
        ToolDefinition(
            name="read_file",
            description="Read the contents of a file from the project workspace.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to project root"},
                },
                "required": ["path"],
            },
            handler=lambda params: _read_file(params, core=core),
            requires_sandbox=False,
            tags=("file", "workspace"),
            required_permission=Permission.TOOL_FILE_READ,
        )
    )

    registry.register(
        ToolDefinition(
            name="write_file",
            description="Write contents to a file in the project workspace.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to project root"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            handler=lambda params: _write_file(params, core=core),
            requires_sandbox=False,
            tags=("file", "workspace"),
            required_permission=Permission.TOOL_FILE_WRITE,
        )
    )

    registry.register(
        ToolDefinition(
            name="list_directory",
            description="List files and subdirectories in a directory.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "default": "",
                        "description": "Path relative to project root",
                    },
                    "recursive": {
                        "type": "boolean",
                        "default": False,
                        "description": "List recursively",
                    },
                },
            },
            handler=lambda params: _list_directory(params, core=core),
            requires_sandbox=False,
            tags=("file", "workspace"),
            required_permission=Permission.TOOL_FILE_READ,
        )
    )

    registry.register(
        ToolDefinition(
            name="search_code",
            description="Search for text or regex patterns in code files.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text or regex pattern to search for",
                    },
                    "file_pattern": {
                        "type": "string",
                        "default": "**/*",
                        "description": "Glob pattern for files",
                    },
                    "regex": {
                        "type": "boolean",
                        "default": False,
                        "description": "Treat query as regex",
                    },
                },
                "required": ["query"],
            },
            handler=lambda params: _search_code(params, core=core),
            requires_sandbox=False,
            tags=("file", "search"),
            required_permission=Permission.TOOL_FILE_READ,
        )
    )

    registry.register(
        ToolDefinition(
            name="run_tests",
            description="Run pytest tests in the project.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "default": ".",
                        "description": "Path to test directory",
                    },
                    "pattern": {
                        "type": "string",
                        "default": "test_*.py",
                        "description": "Test name pattern",
                    },
                    "verbose": {
                        "type": "boolean",
                        "default": False,
                        "description": "Verbose output",
                    },
                },
            },
            handler=lambda params: _run_tests(params, core=core),
            requires_sandbox=True,
            tags=("test", "python"),
            required_permission=Permission.TOOL_SHELL,
        )
    )

    registry.register(
        ToolDefinition(
            name="lint_file",
            description="Lint a Python file with pycodestyle.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to Python file"},
                },
                "required": ["path"],
            },
            handler=lambda params: _lint_file(params, core=core),
            requires_sandbox=True,
            tags=("quality", "lint"),
            required_permission=Permission.TOOL_SHELL,
        )
    )

    registry.register(
        ToolDefinition(
            name="format_code",
            description="Format Python code with black.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to Python file"},
                    "check": {
                        "type": "boolean",
                        "default": False,
                        "description": "Check only, don't modify",
                    },
                },
                "required": ["path"],
            },
            handler=lambda params: _format_code(params, core=core),
            requires_sandbox=True,
            tags=("quality", "format"),
            required_permission=Permission.TOOL_FILE_WRITE,
        )
    )

    registry.register(
        ToolDefinition(
            name="python_exec",
            description="Execute Python code in a sandboxed subprocess and return stdout/stderr.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python source code to execute"},
                },
                "required": ["code"],
            },
            handler=lambda params: _python_exec(params, core=core),
            requires_sandbox=True,
            tags=("code", "execution"),
            required_permission=Permission.TOOL_PYTHON,
        )
    )

    registry.register(
        ToolDefinition(
            name="shell_exec",
            description="Run a shell command in a sandboxed subprocess.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
            handler=lambda params: _shell_exec(params, core=core),
            requires_sandbox=True,
            tags=("shell", "execution"),
            required_permission=Permission.TOOL_SHELL,
        )
    )

    registry.register(
        ToolDefinition(
            name="memory_search",
            description="Search the agent's episodic/semantic/procedural memory.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {"type": "string", "enum": ["episodic", "semantic", "procedural"]},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            handler=lambda params: _memory_search(params, core=core),
            tags=("memory",),
            required_permission=Permission.MEMORY_READ,
        )
    )

    registry.register(
        ToolDefinition(
            name="memory_store",
            description="Store a new memory entry.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "kind": {"type": "string", "enum": ["episodic", "semantic", "procedural"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content"],
            },
            handler=lambda params: _memory_store(params, core=core),
            tags=("memory",),
            required_permission=Permission.MEMORY_WRITE,
        )
    )

    registry.register(
        ToolDefinition(
            name="grep_files",
            description="Search for text in files with line numbers and context.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex to search"},
                    "file_pattern": {
                        "type": "string",
                        "default": "**/*.py",
                        "description": "Glob pattern",
                    },
                    "context": {"type": "integer", "default": 2, "description": "Lines of context"},
                    "regex": {"type": "boolean", "default": False, "description": "Treat as regex"},
                },
                "required": ["query"],
            },
            handler=lambda params: _grep_files(params, core=core),
            requires_sandbox=False,
            tags=("search", "file"),
            required_permission=Permission.TOOL_FILE_READ,
        )
    )

    registry.register(
        ToolDefinition(
            name="file_info",
            description="Get file metadata (size, modified time, type).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to project root"},
                },
                "required": ["path"],
            },
            handler=lambda params: _file_info(params, core=core),
            requires_sandbox=False,
            tags=("file", "metadata"),
            required_permission=Permission.TOOL_FILE_READ,
        )
    )

    registry.register(
        ToolDefinition(
            name="create_directory",
            description="Create a new directory.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to project root",
                    },
                },
                "required": ["path"],
            },
            handler=lambda params: _create_directory(params, core=core),
            requires_sandbox=False,
            tags=("file", "directory"),
            required_permission=Permission.TOOL_FILE_WRITE,
        )
    )

    registry.register(
        ToolDefinition(
            name="delete_file",
            description="Delete a file or directory.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to delete"},
                    "recursive": {
                        "type": "boolean",
                        "default": False,
                        "description": "Delete recursively",
                    },
                },
                "required": ["path"],
            },
            handler=lambda params: _delete_file(params, core=core),
            requires_sandbox=False,
            tags=("file", "delete"),
            required_permission=Permission.TOOL_FILE_WRITE,
        )
    )
