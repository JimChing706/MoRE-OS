# CodeX Improvements — Phase 1: Critical Code Assistant Tools

## Summary of Changes

Added essential file and code assistant tools to MoRE Core's built-in toolset, enabling the system to perform practical software engineering tasks.

## Files Modified

### 1. `more_core/more_core/tools/builtins.py`
Added 6 new tools for code assistance:

| Tool | Description | Parameters |
|------|-------------|------------|
| `read_file` | Read file from project workspace | `path` (required) |
| `write_file` | Write file to project workspace | `path`, `content` (required) |
| `list_directory` | List files in directory | `path`, `recursive` |
| `search_code` | Search text/regex in code files | `query`, `file_pattern`, `regex` |
| `run_tests` | Run pytest tests | `path`, `pattern`, `verbose` |
| `lint_file` | Lint Python file | `path` |
| `format_code` | Format Python code with black | `path`, `check` |

Plus existing:
- `python_exec` — Execute Python code in sandbox (already existed)
- `shell_exec` — Run shell commands in sandbox (already existed)

### 2. `more_core/more_core/runtime/orchestrator.py`
- Added `Path` import
- Added `project_root` attribute to `MoRECore` (from settings)
- Enables file tools to operate within project context

### 3. `more_core/more_core/core/config.py`
- Added `Path` import
- Added `project_root: str | None = None` to `Settings` model

### 4. `more_core/examples/advanced_code_assistant.py` (NEW)
- Full-featured code assistant plugin
- AST-based symbol analysis
- Code navigation and refactoring tools
- Multi-file batch operations
- Test execution integration

## Tool Details

### Security Features
- Path traversal protection (all file ops use `relative_to(root)`)
- Project root isolation
- Hidden directory exclusion (`.git`, `node_modules`, etc.)
- Sandbox execution for test/lint/format tools

### Key Capabilities

1. **File Operations**: Read/write/list with project root enforcement
2. **Code Search**: Text and regex search across project files
3. **Test Execution**: Run pytest with configurable patterns
4. **Linting**: pycodestyle integration (with pylint fallback)
5. **Formatting**: black formatter with check mode

## Testing

All existing tests pass (95/95):
```
================================= 95 passed in 1.40s ===============================
```

New functionality verified through manual testing:
- File read/write operations
- Directory listing (recursive and non-recursive)
- Code search (text and regex)
- Test execution integration
- Linting and formatting

## Integration with Frontend

The app frontend (`app/src/pages/Home.tsx`) can now access these tools through:

```typescript
import { moreEngine } from '@/core/moreEngine';

// Example: Read file
const result = await moreEngine.executeTask({
  type: 'code_generation',
  query: 'read_file',
  targetLayer: 'L0',
});
```

## Next Steps (Phase 2)

1. **AST-based Code Understanding**: Parse Python files to extract symbols, imports, call graphs
2. **Multi-file Edit Coordination**: Batch operations with dependency resolution
3. **Code Generation**: Template-based code generation with type checking
4. **Streaming Support**: Token-by-token LLM output to frontend
5. **Project Indexing**: Background indexing for faster symbol lookup
6. **Git Integration**: Diff, commit, branch operations for version control

## Security Considerations

- All file operations restricted to project root
- No symlink following (prevents escape via symlinks)
- Sandbox execution for Python code and shell commands
- Timeout enforcement on all operations
- Pattern-based skip for sensitive directories

## API Example

```python
from more_core import MoRECore
from more_core.core.types import TaskRequest, TaskType

core = MoRECore.from_env()
await core.start()

# Use new file tools
result = await core.execute(TaskRequest(
    type=TaskType.CODE_GENERATION,
    query="read_file",
    context={"path": "src/main.py"},
    target_layer="L0",
))
```

## Impact

- **Before**: Limited to python_exec and shell_exec only
- **After**: Full file system access with security controls, code search, testing, linting, formatting
- **Developer Experience**: Can now build practical code assistant workflows
- **Extensibility**: Plugin authors can extend with domain-specific tools