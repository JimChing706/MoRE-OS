"""Tests for built-in tools."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestToolRegistry:
    """Test suite for ToolRegistry."""

    def test_import_registry(self):
        """Test registry can be imported."""
        from more_core.tools import registry

        assert registry is not None

    def test_tool_definition(self):
        """Test ToolDefinition exists."""
        from more_core.tools.registry import ToolDefinition

        assert ToolDefinition is not None

    def test_tool_result(self):
        """Test ToolResult exists."""
        from more_core.tools.registry import ToolResult

        assert ToolResult is not None

    def test_registry_class(self):
        """Test ToolRegistry class exists."""
        from more_core.tools.registry import ToolRegistry

        assert ToolRegistry is not None

    def test_registry_instantiation(self):
        """Test registry can be instantiated."""
        from more_core.tools.registry import ToolRegistry

        reg = ToolRegistry()
        assert reg is not None
        assert hasattr(reg, "_tools")


class TestToolsModule:
    """Test suite for tools module."""

    def test_import_builtins(self):
        """Test builtins module can be imported."""
        from more_core.tools import builtins

        assert builtins is not None

    def test_import_tools(self):
        """Test tools module can be imported."""
        from more_core import tools

        assert tools is not None
