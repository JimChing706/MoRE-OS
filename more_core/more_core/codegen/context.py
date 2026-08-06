"""Repo-aware context for code generation.

Scans a project root and produces a compact map of module paths, top-level
definitions, and HTTP routes so the L0 generator can reference existing
code instead of guessing project structure (repo-aware generation).

The output is deliberately compact and capped so prompt-token overhead stays
small.  Any failure (missing root, unparsable module) degrades gracefully to
an empty context, never raising.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Directories that never contribute useful symbols (vendored/build/data).
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "build",
    "dist",
    "data",
    "logs",
    "tests",
    "test",
}

# Decorator attribute names that denote HTTP route registrations.
_ROUTE_ATTRS = ("get", "post", "put", "delete", "patch", "route", "add_api_route")


def _iter_py_files(root: Path, max_files: int) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
        if len(files) >= max_files:
            break
    return files


def _module_summary(root: Path, path: Path) -> str:
    """One-line summary: relative path + top-level symbols + HTTP routes."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return ""
    symbols: list[str] = []
    routes: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(node.name)
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                if dec.func.attr.lower() not in _ROUTE_ATTRS:
                    continue
                if not dec.args:
                    continue
                first = dec.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    routes.append(f"{dec.func.attr.upper()} {first.value}")
        elif isinstance(node, ast.ClassDef):
            symbols.append(node.name)
    parts: list[str] = []
    if symbols:
        parts.append(" ".join(symbols))
    if routes:
        parts.append("routes: " + ", ".join(routes))
    if not parts:
        return ""
    rel = path.relative_to(root).as_posix()
    return f"{rel} :: " + "; ".join(parts)


def build_repo_context(project_root: str | Path | None, *, max_files: int = 30) -> str:
    """Build a compact repo map for code-generation prompts.

    Returns an empty string when *project_root* is missing/invalid or no
    Python modules are found, so callers can append it unconditionally.
    """
    if not project_root:
        return ""
    try:
        root = Path(project_root).resolve()
        if not root.is_dir():
            return ""
    except OSError:
        return ""
    lines: list[str] = []
    for path in _iter_py_files(root, max_files):
        summary = _module_summary(root, path)
        if summary:
            lines.append(f"- {summary}")
    if not lines:
        return ""
    return (
        "<repo_context>\n"
        "Reference structure of the current repository "
        "(module :: top-level symbols; routes: HTTP METHOD path):\n"
        + "\n".join(lines)
        + "\n</repo_context>"
    )
