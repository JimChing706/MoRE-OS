"""CodeX Phase 2: AST-based Code Indexing and Symbol Lookup

This module provides advanced code indexing capabilities using Python AST.
"""
from __future__ import annotations

import ast
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from threading import RLock


@dataclass
class SymbolLocation:
    """Location of a symbol in source code."""
    file_path: str
    lineno: int
    end_lineno: int
    col_offset: int
    end_col_offset: int
    symbol_type: str  # 'function', 'class', 'method', 'import', 'variable', 'decorator'
    name: str
    qualified_name: str = ""
    docstring: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file_path,
            "line": self.lineno,
            "end_line": self.end_lineno,
            "col": self.col_offset,
            "end_col": self.end_col_offset,
            "type": self.symbol_type,
            "name": self.name,
            "qualified": self.qualified_name,
            "doc": self.docstring[:100] if self.docstring else "",
            "signature": self.signature,
        }


@dataclass
class ImportInfo:
    """Information about an import statement."""
    module: str
    names: List[str]
    level: int  # 0 for absolute, >0 for relative
    lineno: int


@dataclass
class FileIndex:
    """Index data for a single file."""
    file_path: str
    file_hash: str
    mtime: float
    size: int
    line_count: int
    symbols: List[SymbolLocation] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    indexed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.file_path,
            "hash": self.file_hash,
            "mtime": self.mtime,
            "size": self.size,
            "lines": self.line_count,
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": [
                {"module": i.module, "names": i.names, "level": i.level, "line": i.lineno}
                for i in self.imports
            ],
            "errors": self.errors,
            "indexed_at": self.indexed_at,
        }


class ASTSymbolExtractor(ast.NodeVisitor):
    """AST visitor for extracting symbols from Python source."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.symbols: List[SymbolLocation] = []
        self.imports: List[ImportInfo] = []
        self.errors: List[str] = []
        self.current_class: Optional[str] = None
        self.current_module: str = ""

    def visit_Module(self, node: ast.Module) -> None:
        self.current_module = ""
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self.current_class
        self.current_class = node.name if not self.current_module else f"{self.current_module}.{node.name}"

        docstring = ast.get_docstring(node) or ""

        self.symbols.append(SymbolLocation(
            file_path=self.file_path,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno),
            col_offset=node.col_offset,
            end_col_offset=getattr(node, "end_col_offset", node.col_offset),
            symbol_type="class",
            name=node.name,
            qualified_name=self.current_class,
            docstring=docstring,
        ))

        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, "function")

    def _visit_function(self, node: ast.FunctionDef, base_type: str) -> None:
        is_method = self.current_class is not None
        sym_type = "method" if is_method else base_type

        docstring = ast.get_docstring(node) or ""

        args = node.args
        defaults = len(args.defaults)
        posonly = len(args.posonlyargs)

        params = []
        for i, arg in enumerate(args.args):
            default_val = ""
            if i >= posonly + (len(args.args) - defaults):
                idx = i - (len(args.args) - defaults)
                if idx < len(args.defaults):
                    default_val = f"={repr(args.defaults[idx])}"
            params.append(f"{arg.arg}{default_val}")

        if args.vararg:
            params.append(f"*{args.vararg.arg}")
        if args.kwarg:
            params.append(f"**{args.kwarg.arg}")

        signature = f"({', '.join(params)})"

        qualified = (
            f"{self.current_class}.{node.name}"
            if self.current_class
            else f"{self.current_module}.{node.name}" if self.current_module else node.name
        )

        self.symbols.append(SymbolLocation(
            file_path=self.file_path,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno),
            col_offset=node.col_offset,
            end_col_offset=getattr(node, "end_col_offset", node.col_offset),
            symbol_type=sym_type,
            name=node.name,
            qualified_name=qualified,
            docstring=docstring,
            signature=signature,
        ))

        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(ImportInfo(
                module=alias.name,
                names=[alias.asname or alias.name],
                level=0,
                lineno=node.lineno,
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        self.imports.append(ImportInfo(
            module=module,
            names=[a.asname or a.name for a in node.names],
            level=node.level,
            lineno=node.lineno,
        ))

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.symbols.append(SymbolLocation(
                    file_path=self.file_path,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    col_offset=node.col_offset,
                    end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                    symbol_type="assignment",
                    name=target.id,
                    qualified_name=(
                        f"{self.current_class}.{target.id}"
                        if self.current_class
                        else target.id
                    ),
                ))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            docstring = ast.get_docstring(node) or ""
            self.symbols.append(SymbolLocation(
                file_path=self.file_path,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", node.lineno),
                col_offset=node.col_offset,
                end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                symbol_type="annotated_assignment",
                name=node.target.id,
                qualified_name=(
                    f"{self.current_class}.{node.target.id}"
                    if self.current_class
                    else node.target.id
                ),
                docstring=docstring,
            ))
        self.generic_visit(node)


class CodeIndex:
    """High-performance code index with AST-based symbol extraction."""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path.cwd()
        self._file_index: Dict[str, FileIndex] = {}
        self._symbol_map: Dict[str, List[SymbolLocation]] = {}  # name -> locations
        self._qualified_map: Dict[str, SymbolLocation] = {}  # qualified name -> location
        self._import_graph: Dict[str, Set[str]] = {}  # file -> set of imported modules
        self._lock = RLock()

    def index_file(self, file_path: Path) -> FileIndex:
        """Index a single Python file."""
        with self._lock:
            try:
                rel_path = file_path.relative_to(self.project_root)
            except ValueError:
                raise ValueError(f"File {file_path} is outside project root {self.project_root}")

            content = file_path.read_text(encoding="utf-8")
            stat = file_path.stat()

            file_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            tree = ASTSymbolExtractor(str(rel_path))
            try:
                ast.parse(content, filename=str(file_path))
                tree.visit(ast.parse(content))
            except SyntaxError as e:
                tree.errors.append(f"Syntax error at line {e.lineno}: {e.msg}")

            idx = FileIndex(
                file_path=str(rel_path),
                file_hash=file_hash,
                mtime=stat.st_mtime,
                size=stat.st_size,
                line_count=len(content.splitlines()),
                symbols=tree.symbols,
                imports=tree.imports,
                errors=tree.errors,
            )

            self._file_index[str(rel_path)] = idx

            for sym in tree.symbols:
                if sym.name not in self._symbol_map:
                    self._symbol_map[sym.name] = []
                self._symbol_map[sym.name].append(sym)

                if sym.qualified_name:
                    self._qualified_map[sym.qualified_name] = sym

            if tree.imports:
                imported_modules = set()
                for imp in tree.imports:
                    if imp.level == 0:
                        imported_modules.add(imp.module.split('.')[0])
                self._import_graph[str(rel_path)] = imported_modules

            return idx

    def index_directory(self, dir_path: Optional[Path] = None, pattern: str = "**/*.py") -> int:
        """Index all Python files in a directory."""
        root = dir_path or self.project_root
        count = 0
        for py_file in root.glob(pattern):
            if any(skip in py_file.parts for skip in {".git", "node_modules", "__pycache__", "venv", ".venv", ".pytest_cache", ".ruff_cache"}):
                continue
            if py_file.is_file():
                try:
                    self.index_file(py_file)
                    count += 1
                except Exception:
                    pass
        return count

    def find_symbol(self, name: str, exact: bool = False) -> List[SymbolLocation]:
        """Find symbols by name."""
        with self._lock:
            if exact:
                return [loc for loc in self._symbol_map.get(name, []) if loc.name == name]
            return self._symbol_map.get(name, [])

    def find_by_qualified_name(self, qualified_name: str) -> Optional[SymbolLocation]:
        """Find symbol by fully qualified name."""
        with self._lock:
            return self._qualified_map.get(qualified_name)

    def find_in_file(self, file_path: str) -> List[SymbolLocation]:
        """Find all symbols in a specific file."""
        with self._lock:
            idx = self._file_index.get(file_path)
            return idx.symbols if idx else []

    def get_imports(self, file_path: str) -> List[ImportInfo]:
        """Get imports for a file."""
        with self._lock:
            idx = self._file_index.get(file_path)
            return idx.imports if idx else []

    def get_file_stats(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get statistics for an indexed file."""
        with self._lock:
            idx = self._file_index.get(file_path)
            if idx:
                return {
                    "path": idx.file_path,
                    "hash": idx.file_hash,
                    "size": idx.size,
                    "lines": idx.line_count,
                    "symbols": len(idx.symbols),
                    "classes": sum(1 for s in idx.symbols if s.symbol_type == "class"),
                    "functions": sum(1 for s in idx.symbols if s.symbol_type in ("function", "method")),
                    "imports": len(idx.imports),
                    "indexed_at": idx.indexed_at,
                }
            return None

    def search_symbols(self, query: str, file_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search symbols by name pattern."""
        with self._lock:
            results = []
            for name, locations in self._symbol_map.items():
                if query.lower() in name.lower():
                    for loc in locations:
                        if file_filter and loc.file_path != file_filter:
                            continue
                        results.append({
                            "name": loc.name,
                            "qualified": loc.qualified_name,
                            "file": loc.file_path,
                            "line": loc.lineno,
                            "type": loc.symbol_type,
                            "doc": loc.docstring[:100] if loc.docstring else "",
                        })
            return results[:50]

    def get_call_graph(self, file_path: str) -> Dict[str, List[str]]:
        """Build a simple call graph for a file."""
        with self._lock:
            idx = self._file_index.get(file_path)
            if not idx:
                return {}

            graph: Dict[str, List[str]] = {}
            content = Path(self.project_root / file_path).read_text()

            for sym in idx.symbols:
                if sym.symbol_type in ("function", "method"):
                    graph[sym.qualified_name] = []

            for node in ast.walk(ast.parse(content)):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in self._symbol_map:
                            for sym in idx.symbols:
                                if sym.symbol_type in ("function", "method") and sym.qualified_name:
                                    graph[sym.qualified_name].append(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name):
                            name = f"{node.func.value.id}.{node.func.attr}"
                            if name in self._qualified_map:
                                for sym in idx.symbols:
                                    if sym.symbol_type in ("function", "method") and sym.qualified_name:
                                        graph[sym.qualified_name].append(name)

            return graph

    def is_stale(self, file_path: str) -> bool:
        """Check if a file index is stale (file modified since indexing)."""
        with self._lock:
            idx = self._file_index.get(file_path)
            if not idx:
                return True
            actual_file = self.project_root / file_path
            if not actual_file.exists():
                return True
            return actual_file.stat().st_mtime > idx.mtime

    def invalidate(self, file_path: str) -> None:
        """Remove a file from the index."""
        with self._lock:
            if file_path in self._file_index:
                del self._file_index[file_path]

            for sym_name, locations in list(self._symbol_map.items()):
                self._symbol_map[sym_name] = [loc for loc in locations if loc.file_path != file_path]
                if not self._symbol_map[sym_name]:
                    del self._symbol_map[sym_name]

            for qname in list(self._qualified_map.keys()):
                if self._qualified_map[qname].file_path == file_path:
                    del self._qualified_map[qname]

            if file_path in self._import_graph:
                del self._import_graph[file_path]

    def export_json(self) -> str:
        """Export the index as JSON."""
        with self._lock:
            data = {
                "project_root": str(self.project_root),
                "file_count": len(self._file_index),
                "symbol_count": sum(len(v) for v in self._symbol_map.values()),
                "files": {path: idx.to_dict() for path, idx in self._file_index.items()},
            }
            return json.dumps(data, indent=2)

    def import_json(self, json_str: str) -> None:
        """Import a JSON index."""
        with self._lock:
            data = json.loads(json_str)
            self.project_root = Path(data["project_root"])
            self._file_index.clear()
            self._symbol_map.clear()
            self._qualified_map.clear()
            self._import_graph.clear()

            for path, idx_data in data["files"].items():
                self._file_index[path] = FileIndex(
                    file_path=idx_data["path"],
                    file_hash=idx_data["hash"],
                    mtime=idx_data["mtime"],
                    size=idx_data["size"],
                    line_count=idx_data["lines"],
                    indexed_at=idx_data.get("indexed_at", time.time()),
                )
                for sym_data in idx_data.get("symbols", []):
                    sym = SymbolLocation(**sym_data)
                    if sym.name not in self._symbol_map:
                        self._symbol_map[sym.name] = []
                    self._symbol_map[sym.name].append(sym)
                    if sym.qualified_name:
                        self._qualified_map[sym.qualified_name] = sym


# Global index instance
_global_index: Optional[CodeIndex] = None


def get_code_index(project_root: Optional[Path] = None) -> CodeIndex:
    """Get the global code index instance."""
    global _global_index
    if _global_index is None:
        _global_index = CodeIndex(project_root)
    return _global_index