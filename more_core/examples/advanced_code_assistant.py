"""Advanced Code Assistant Plugin

A production-ready code assistant that integrates with the MoRE Core platform
to provide intelligent code analysis, refactoring, testing, and review capabilities.

Features:
- File and project-aware code operations
- AST-based symbol analysis
- Multi-file edit planning
- Automated test execution
- Code quality checking
"""
from __future__ import annotations

import ast
import json
from typing import Dict, List, Any, Optional

from more_core.plugins.sdk import PluginBase, PluginContext


class SymbolInfo:
    """Information about a code symbol (function, class, etc.)."""
    def __init__(self, name: str, kind: str, lineno: int, end_lineno: int,
                 col_offset: int, end_col_offset: int, docstring: str = "",
                 children: List['SymbolInfo'] | None = None):
        self.name = name
        self.kind = kind  # 'function', 'class', 'import', 'variable'
        self.lineno = lineno
        self.end_lineno = end_lineno
        self.col_offset = col_offset
        self.end_col_offset = end_col_offset
        self.docstring = docstring
        self.children = children or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'kind': self.kind,
            'lineno': self.lineno,
            'end_lineno': self.end_lineno,
            'col_offset': self.col_offset,
            'end_col_offset': self.end_col_offset,
            'docstring': self.docstring,
            'children': [c.to_dict() for c in self.children],
        }


class CodeAnalyzer(ast.NodeVisitor):
    """AST-based code analyzer for extracting symbols and dependencies."""

    def __init__(self):
        self.symbols: List[SymbolInfo] = []
        self.imports: List[str] = []
        self.current_class: Optional[SymbolInfo] = None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        docstring = ast.get_docstring(node) or ""
        symbol = SymbolInfo(
            name=node.name,
            kind="class",
            lineno=node.lineno,
            end_lineno=getattr(node, 'end_lineno', node.lineno),
            col_offset=node.col_offset,
            end_col_offset=getattr(node, 'end_col_offset', node.col_offset),
            docstring=docstring,
        )
        old_class = self.current_class
        self.current_class = symbol
        self.generic_visit(node)
        self.current_class = old_class
        self.symbols.append(symbol)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        docstring = ast.get_docstring(node) or ""
        children: List[SymbolInfo] = []

        # Get arguments
        args_info = []
        for arg in node.args.args:
            args_info.append(arg.arg)

        symbol = SymbolInfo(
            name=node.name,
            kind="function",
            lineno=node.lineno,
            end_lineno=getattr(node, 'end_lineno', node.lineno),
            col_offset=node.col_offset,
            end_col_offset=getattr(node, 'end_col_offset', node.col_offset),
            docstring=docstring,
            children=children,
        )
        if self.current_class:
            self.current_class.children.append(symbol)
        else:
            self.symbols.append(symbol)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.imports.append(f"{module}.{alias.name}" if module else alias.name)
        self.generic_visit(node)


class CodeAssistantPlugin(PluginBase):
    """Advanced code assistant plugin for MoRE Core."""

    NAME = "advanced_code_assistant"
    VERSION = "0.2.0"
    DESCRIPTION = "Intelligent code analysis, refactoring, and testing assistant"
    AUTHOR = "MoRE Core Team"
    CAPABILITIES = (
        "code_analysis",
        "code_navigation",
        "symbol_lookup",
        "code_refactoring",
        "test_execution",
        "linting",
        "formatting",
        "multi_file_ops",
    )
    DEPENDENCIES = ()

    def __init__(self) -> None:
        super().__init__()
        self._code_index: Dict[str, List[SymbolInfo]] = {}
        self._file_cache: Dict[str, str] = {}

    async def activate(self, ctx: PluginContext) -> None:
        """Activate the plugin and register code assistant tools."""
        await super().activate(ctx)
        
        # Register custom code assistant tools
        self.core.tools.register(
            self._create_analyze_code_tool()
        )
        self.core.tools.register(
            self._create_find_symbol_tool()
        )
        self.core.tools.register(
            self._create_refactor_tool()
        )
        self.core.tools.register(
            self._create_test_generator_tool()
        )
        self.core.tools.register(
            self._create_code_review_tool()
        )
        self.core.tools.register(
            self._create_batch_edit_tool()
        )

        # Subscribe to file change events to update index
        self.core.event_bus.subscribe("file.changed", self._on_file_changed)
        
        self.core.logger.info("Advanced Code Assistant plugin activated")

    async def deactivate(self) -> None:
        """Deactivate the plugin."""
        await super().deactivate()

    def _create_analyze_code_tool(self) -> Any:
        """Create tool for analyzing Python files."""
        from more_core.tools.registry import ToolDefinition
        
        async def handler(params: Dict[str, Any]) -> Any:
            from more_core.tools.registry import ToolResult
            path = params.get("path", "")
            if not path:
                return ToolResult(tool="analyze_code", success=False, error="path required")
            
            # Read file
            read_result = await self.core.tools.execute("read_file", {"path": path})
            if not read_result.success:
                from more_core.tools.registry import ToolResult
                return ToolResult(
                    tool="analyze_code",
                    success=False,
                    error=f"cannot read file: {read_result.error}"
                )
            
            content = read_result.output
            
            # Parse AST
            try:
                tree = ast.parse(content)
                analyzer = CodeAnalyzer()
                analyzer.visit(tree)
                
                self._code_index[path] = analyzer.symbols
                
                # Count statistics
                num_classes = sum(1 for s in analyzer.symbols if s.kind == "class")
                num_functions = sum(1 for s in analyzer.symbols if s.kind == "function")
                num_imports = len(analyzer.imports)
                
                result = {
                    "file": path,
                    "statistics": {
                        "classes": num_classes,
                        "functions": num_functions,
                        "imports": num_imports,
                        "lines": len(content.split('\n')),
                        "characters": len(content),
                    },
                    "symbols": [s.to_dict() for s in analyzer.symbols],
                    "imports": analyzer.imports,
                }
                
                from more_core.tools.registry import ToolResult
                return ToolResult(
                    tool="analyze_code",
                    success=True,
                    output=json.dumps(result, indent=2)
                )
            except SyntaxError as e:
                from more_core.tools.registry import ToolResult
                return ToolResult(
                    tool="analyze_code",
                    success=False,
                    error=f"syntax error: {e.msg} at line {e.lineno}"
                )
        
        return ToolDefinition(
            name="analyze_code",
            description="Analyze a Python file and extract symbols, imports, and statistics.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to Python file"},
                },
                "required": ["path"],
            },
            handler=handler,
            requires_sandbox=False,
            tags=("code", "analysis"),
        )

    def _create_find_symbol_tool(self) -> Any:
        """Create tool for finding symbols across the codebase."""
        from more_core.tools.registry import ToolDefinition
        
        async def handler(params: Dict[str, Any]) -> Any:
            from more_core.tools.registry import ToolResult
            symbol_name = params.get("name", "")
            symbol_type = params.get("type", "")  # function, class, import
            
            if not symbol_name:
                return ToolResult(
                    tool="find_symbol",
                    success=False,
                    error="symbol name required"
                )
            
            matches = []
            # Search in indexed files
            for file_path, symbols in self._code_index.items():
                for symbol in symbols:
                    if symbol_name in symbol.name:
                        if not symbol_type or symbol.kind == symbol_type:
                            matches.append({
                                "file": file_path,
                                "name": symbol.name,
                                "type": symbol.kind,
                                "line": symbol.lineno,
                                "docstring": symbol.docstring[:100] if symbol.docstring else "",
                            })
            
            # Also search via grep for unindexed files
            if len(matches) < 5:
                search_result = await self.core.tools.execute("search_code", {
                    "query": symbol_name,
                    "regex": False,
                    "file_pattern": "**/*.py",
                })
                if search_result.success:
                    try:
                        search_data = json.loads(search_result.output)
                        for match in search_data.get("matches", []):
                            existing = any(
                                m["file"] == match["file"] and m["line"] == match["line"]
                                for m in matches
                            )
                            if not existing:
                                matches.append({
                                    "file": match["file"],
                                    "name": symbol_name,
                                    "type": "unknown",
                                    "line": match["line"],
                                    "docstring": "",
                                })
                    except (json.JSONDecodeError, KeyError):
                        pass
            
            return ToolResult(
                tool="find_symbol",
                success=True,
                output=json.dumps({
                    "symbol": symbol_name,
                    "count": len(matches),
                    "matches": matches[:20],
                }, indent=2)
            )
        
        return ToolDefinition(
            name="find_symbol",
            description="Find a symbol by name across the codebase.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Symbol name to search for"},
                    "type": {"type": "string", "enum": ["function", "class", "import"], "description": "Symbol type filter"},
                },
                "required": ["name"],
            },
            handler=handler,
            requires_sandbox=False,
            tags=("code", "navigation"),
        )

    def _create_refactor_tool(self) -> Any:
        """Create tool for refactoring code."""
        from more_core.tools.registry import ToolDefinition
        
        async def handler(params: Dict[str, Any]) -> Any:
            from more_core.tools.registry import ToolResult
            
            path = params.get("path", "")
            refactor_type = params.get("type", "")  # rename, extract, inline
            target = params.get("target", "")
            new_value = params.get("new_value", "")
            
            if not path or not refactor_type or not target:
                return ToolResult(
                    tool="refactor",
                    success=False,
                    error="path, type, and target are required"
                )
            
            # Read file
            read_result = await self.core.tools.execute("read_file", {"path": path})
            if not read_result.success:
                return ToolResult(
                    tool="refactor",
                    success=False,
                    error=f"cannot read file: {read_result.error}"
                )
            
            content = read_result.output

            if refactor_type == "rename":
                # Simple rename: replace all occurrences
                if not new_value:
                    return ToolResult(
                        tool="refactor",
                        success=False,
                        error="new_value required for rename"
                    )
                
                new_content = content.replace(target, new_value)
                if new_content == content:
                    return ToolResult(
                        tool="refactor",
                        success=False,
                        error=f"target '{target}' not found"
                    )
                
                # Write back
                write_result = await self.core.tools.execute("write_file", {
                    "path": path,
                    "content": new_content,
                })
                if not write_result.success:
                    return ToolResult(
                        tool="refactor",
                        success=False,
                        error=f"cannot write file: {write_result.error}"
                    )
                
                return ToolResult(
                    tool="refactor",
                    success=True,
                    output=f"Renamed '{target}' to '{new_value}' in {path}"
                )
            
            elif refactor_type == "format":
                # Format with black
                format_result = await self.core.tools.execute("format_code", {
                    "path": path,
                    "check": False,
                })
                if not format_result.success:
                    return ToolResult(
                        tool="refactor",
                        success=False,
                        error=f"formatting failed: {format_result.error}"
                    )
                return ToolResult(
                    tool="refactor",
                    success=True,
                    output=format_result.output
                )
            
            elif refactor_type == "lint":
                # Lint file
                lint_result = await self.core.tools.execute("lint_file", {
                    "path": path,
                })
                if not lint_result.success:
                    return ToolResult(
                        tool="refactor",
                        success=False,
                        error=f"linting failed: {lint_result.error}"
                    )
                return ToolResult(
                    tool="refactor",
                    success=True,
                    output=lint_result.output
                )
            
            else:
                return ToolResult(
                    tool="refactor",
                    success=False,
                    error=f"unknown refactor type: {refactor_type}"
                )
        
        return ToolDefinition(
            name="refactor",
            description="Refactor code (rename, format, lint).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "type": {"type": "string", "enum": ["rename", "format", "lint"], "description": "Refactor type"},
                    "target": {"type": "string", "description": "Target symbol (for rename)"},
                    "new_value": {"type": "string", "description": "New value (for rename)"},
                },
                "required": ["path", "type"],
            },
            handler=handler,
            requires_sandbox=False,
            tags=("code", "refactoring"),
        )

    def _create_test_generator_tool(self) -> Any:
        """Create tool for running tests."""
        from more_core.tools.registry import ToolDefinition
        
        async def handler(params: Dict[str, Any]) -> Any:
            from more_core.tools.registry import ToolResult
            
            path = params.get("path", ".")
            pattern = params.get("pattern", "test_*.py")
            verbose = params.get("verbose", False)
            
            test_result = await self.core.tools.execute("run_tests", {
                "path": path,
                "pattern": pattern,
                "verbose": verbose,
            })
            
            if not test_result.success:
                return ToolResult(
                    tool="run_tests",
                    success=False,
                    error=test_result.error or "tests failed"
                )
            
            return ToolResult(
                tool="run_tests",
                success=True,
                output=test_result.output or "tests passed"
            )
        
        return ToolDefinition(
            name="run_tests",
            description="Run pytest tests.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": ".", "description": "Test path"},
                    "pattern": {"type": "string", "default": "test_*.py", "description": "Test pattern"},
                    "verbose": {"type": "boolean", "default": False, "description": "Verbose output"},
                },
            },
            handler=handler,
            requires_sandbox=True,
            tags=("test", "python"),
        )

    def _create_code_review_tool(self) -> Any:
        """Create tool for code review."""
        from more_core.tools.registry import ToolDefinition
        
        async def handler(params: Dict[str, Any]) -> Any:
            from more_core.tools.registry import ToolResult
            
            path = params.get("path", "")
            if not path:
                return ToolResult(
                    tool="code_review",
                    success=False,
                    error="path required"
                )
            
            # Analyze code
            analyze_result = await self.core.tools.execute("analyze_code", {"path": path})
            if not analyze_result.success:
                return ToolResult(
                    tool="code_review",
                    success=False,
                    error=f"analysis failed: {analyze_result.error}"
                )
            
            # Lint code
            lint_result = await self.core.tools.execute("lint_file", {"path": path})
            
            # Read file
            read_result = await self.core.tools.execute("read_file", {"path": path})
            if not read_result.success:
                return ToolResult(
                    tool="code_review",
                    success=False,
                    error=f"cannot read file: {read_result.error}"
                )
            
            lines = len(read_result.output.split('\n'))
            
            review = {
                "file": path,
                "lines": lines,
                "analysis": json.loads(analyze_result.output) if analyze_result.success else {},
                "lint_issues": lint_result.output if lint_result.success else "No linter available",
                "summary": {
                    "quality": "good" if lint_result.success else "unknown",
                    "maintainability": "review manually",
                }
            }
            
            return ToolResult(
                tool="code_review",
                success=True,
                output=json.dumps(review, indent=2)
            )
        
        return ToolDefinition(
            name="code_review",
            description="Perform code review (analysis, linting, quality check).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to review"},
                },
                "required": ["path"],
            },
            handler=handler,
            requires_sandbox=False,
            tags=("code", "review"),
        )

    def _create_batch_edit_tool(self) -> Any:
        """Create tool for batch file operations."""
        from more_core.tools.registry import ToolDefinition
        
        async def handler(params: Dict[str, Any]) -> Any:
            from more_core.tools.registry import ToolResult
            
            operations = params.get("operations", [])
            if not operations:
                return ToolResult(
                    tool="batch_edit",
                    success=False,
                    error="operations list required"
                )
            
            results = []
            failed = 0
            
            for op in operations:
                op_type = op.get("type")
                path = op.get("path")
                
                if op_type == "read":
                    result = await self.core.tools.execute("read_file", {"path": path})
                    results.append({"op": "read", "path": path, "success": result.success})
                    if not result.success:
                        failed += 1
                elif op_type == "write":
                    result = await self.core.tools.execute("write_file", {
                        "path": path,
                        "content": op.get("content", ""),
                    })
                    results.append({"op": "write", "path": path, "success": result.success})
                    if not result.success:
                        failed += 1
                elif op_type == "list":
                    result = await self.core.tools.execute("list_directory", {
                        "path": path,
                        "recursive": op.get("recursive", False),
                    })
                    results.append({"op": "list", "path": path, "success": result.success})
                    if not result.success:
                        failed += 1
            
            return ToolResult(
                tool="batch_edit",
                success=failed == 0,
                output=json.dumps({
                    "total": len(operations),
                    "success": len(operations) - failed,
                    "failed": failed,
                    "results": results,
                }, indent=2)
            )
        
        return ToolDefinition(
            name="batch_edit",
            description="Perform batch file operations (read, write, list).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["read", "write", "list"]},
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                                "recursive": {"type": "boolean"},
                            },
                            "required": ["type", "path"],
                        },
                    },
                },
                "required": ["operations"],
            },
            handler=handler,
            requires_sandbox=False,
            tags=("file", "batch"),
        )

    async def _on_file_changed(self, event: Any) -> None:
        """Handle file change events."""
        path = event.data.get("path") if event.data else None
        if path and path in self._code_index:
            del self._code_index[path]
            self.core.logger.debug(f"Invalidated index for {path}")


# Legacy function for backward compatibility
plugin = CodeAssistantPlugin
