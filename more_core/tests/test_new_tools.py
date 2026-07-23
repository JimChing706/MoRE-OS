"""Tests for new file/code assistant tools."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest



@pytest.fixture
def temp_project():
    """Create a temporary project with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "test_file.py").write_text("""
def hello(name):
    '''Say hello to someone.'''
    return f"Hello {name}!"

class Greeter:
    def __init__(self, greeting):
        self.greeting = greeting
    
    def greet(self, target):
        return f"{self.greeting}, {target}!"
""")
        sub = root / "subdir"
        sub.mkdir()
        (sub / "utils.py").write_text("def add(a, b): return a + b\n")
        yield root


@pytest.fixture
def more_core_with_tools():
    """Create a minimal MoRECore instance for testing tools."""
    from more_core.core.config import Settings
    from more_core.runtime.orchestrator import MoRECore
    
    settings = Settings(
        plugin_dir="tests/plugins",
        log_dir="tests/logs",
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
    )
    return MoRECore(settings)


@pytest.fixture
def core_with_project_root(more_core_with_tools, temp_project):
    """MoRECore with project root set."""
    more_core_with_tools.settings.project_root = str(temp_project)
    more_core_with_tools.project_root = Path(str(temp_project))
    return more_core_with_tools

def test_read_file(core_with_project_root):
    """Test reading a file."""
    from more_core.tools.builtins import _read_file
    import asyncio
    result = asyncio.run(_read_file({"path": "test_file.py"}, core=core_with_project_root))
    assert result.success
    assert "def hello" in result.output
    assert "class Greeter" in result.output

def test_read_file_not_found(core_with_project_root):
    """Test reading non-existent file."""
    from more_core.tools.builtins import _read_file
    import asyncio
    result = asyncio.run(_read_file({"path": "nonexistent.py"}, core=core_with_project_root))
    assert not result.success
    assert "not found" in result.error.lower()

def test_write_file(core_with_project_root, temp_project):
    """Test writing a file."""
    from more_core.tools.builtins import _write_file
    import asyncio
    result = asyncio.run(_write_file({
        "path": "new_file.py",
        "content": "print('test')",
    }, core=core_with_project_root))
    assert result.success
    target = temp_project / "new_file.py"
    assert target.exists()
    assert target.read_text() == "print('test')"

def test_list_directory(core_with_project_root):
    """Test listing a directory."""
    from more_core.tools.builtins import _list_directory
    import asyncio
    result = asyncio.run(_list_directory({"recursive": False}, core=core_with_project_root))
    assert result.success
    data = json.loads(result.output)
    assert len(data) >= 2

def test_list_directory_recursive(core_with_project_root):
    """Test recursive directory listing."""
    from more_core.tools.builtins import _list_directory
    import asyncio
    result = asyncio.run(_list_directory({"recursive": True}, core=core_with_project_root))
    assert result.success
    data = json.loads(result.output)
    paths = [item["path"] for item in data]
    assert any("utils.py" in p for p in paths)

def test_search_code(core_with_project_root):
    """Test searching for code."""
    import asyncio
    from more_core.tools.builtins import _search_code
    result = asyncio.run(_search_code({
        "query": "def hello",
        "file_pattern": "**/*.py",
        "regex": True
    }, core=core_with_project_root))
    assert result.success
    data = json.loads(result.output)
    assert data["total_matches"] >= 1
    matches = data["matches"]
    assert any("def hello" in m["text"] for m in matches)

def test_search_code_regex(core_with_project_root):
    """Test regex search."""
    import asyncio
    from more_core.tools.builtins import _search_code
    result = asyncio.run(_search_code({
        "query": r"def \w+",
        "regex": True,
    }, core=core_with_project_root))
    assert result.success
    data = json.loads(result.output)
    assert data["total_matches"] >= 1

def test_run_basic_tests(core_with_project_root):
    """Test running pytest."""
    import asyncio
    from more_core.tools.builtins import _run_tests
    result = asyncio.run(_run_tests({
        "path": ".", "pattern": "test_*.py", "verbose": False,
    }, core=core_with_project_root))
    assert result is not None

def test_lint_file(core_with_project_root):
    """Test linting a file."""
    import asyncio
    from more_core.tools.builtins import _lint_file
    result = asyncio.run(_lint_file({"path": "test_file.py"}, core=core_with_project_root))
    assert result is not None

def test_format_code(core_with_project_root):
    """Test formatting code."""
    import asyncio
    from more_core.tools.builtins import _format_code
    result = asyncio.run(_format_code({
        "path": "test_file.py", "check": False,
    }, core=core_with_project_root))
    assert result is not None

def test_tool_registration(more_core_with_tools):
    """Test that built-in tools can be registered."""
    from more_core.tools.builtins import register_builtins
    from more_core.tools.registry import ToolRegistry
    registry = ToolRegistry()
    register_builtins(registry, more_core_with_tools)
    tool_names = [t.name for t in registry.list_tools()]
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "list_directory" in tool_names
    assert "search_code" in tool_names
    assert "run_tests" in tool_names
    assert "lint_file" in tool_names
    assert "format_code" in tool_names

@pytest.mark.asyncio
async def test_execute_tools_via_registry(core_with_project_root):
    """Test executing tools through the registry."""
    from more_core.tools.builtins import register_builtins
    register_builtins(core_with_project_root.tools, core_with_project_root)
    result = await core_with_project_root.tools.invoke(
        "read_file", {"path": "test_file.py"}
    )
    assert result.success
    assert "def hello" in result.output
    assert "class Greeter" in result.output
