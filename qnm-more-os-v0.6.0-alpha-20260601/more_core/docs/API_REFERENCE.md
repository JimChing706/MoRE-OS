# MoRE OS API Reference

## Core Components

### MoRECore

```python
from more_core import MoRECore
from more_core.core.config import Settings

# Initialize
settings = Settings(
    providers=[...],
    fallback_chain=[...],
)
core = MoRECore(settings)

# Execute task
result = await core.execute(request)
```

### TaskRequest

```python
from more_core.core.types import TaskRequest, TaskType

request = TaskRequest(
    type=TaskType.NLP_TASK,
    query="Your question here"
)
```

---

## LLM Management

### LLMManager

```python
from more_core.llm.manager import LLMManager
from more_core.core.config import LLMProviderConfig

# Configure providers
providers = [
    LLMProviderConfig(
        provider="ollama",
        name="ollama",
        endpoint="http://localhost:11434",
        model="llama2"
    ),
    LLMProviderConfig(
        provider="lmstudio",
        name="lmstudio", 
        endpoint="http://localhost:1234",
        model="local-model",
    )
]

manager = LLMManager(providers=providers, fallback_chain=["ollama", "lmstudio"])

# Generate
response = await manager.generate(request)
```

### LLMStateManager

```python
from more_core.llm.state_manager import LLMStateManager

state_manager = LLMStateManager()

# Get current state
state = state_manager.get_state()

# Update parameters
state_manager.update_state(temperature=0.8, max_tokens=2048)

# Get usage stats
stats = state_manager.get_usage()
```

---

## Layer System

### Layers (L0-L5)

| Layer | Purpose | Key Classes |
|-------|---------|-------------|
| L0 | Execution | `ExecutionLayer` |
| L1 | Orchestration | `OrchestrationLayer` |
| L2 | Evolution | `EvolutionLayer`, `DGMEvolution` |
| L3 | Symbolic | `SymbolicLayer` |
| L4 | Cognition | `CognitionLayer` |
| L5 | Metacognition | `MetacognitionLayer`, `HyperAgent` |

---

## Tools

### ToolRegistry

```python
from more_core.tools.registry import ToolRegistry, ToolDefinition, ToolResult

registry = ToolRegistry()

# Register tool
registry.register(ToolDefinition(
    name="my_tool",
    description="My custom tool",
    parameters_schema={...},
    handler=async_func
))

# Execute
result = await registry.execute("my_tool", {"param": "value"})
```

### Built-in Tools

| Tool | Description |
|------|-------------|
| `echo` | Echo input back |
| `calculator` | Evaluate math expression |
| `web_search` | Search web (stub) |
| `code_execution` | Run Python code |
| `read_file` | Read file contents |
| `write_file` | Write file |
| `list_directory` | List directory contents |
| `grep_files` | Search in files |
| `file_info` | Get file metadata |
| `create_directory` | Create directory |
| `delete_file` | Delete file |

---

## Governance

### RBAC

```python
from more_core.governance.rbac import RBACPolicy, User, Role, Permission

policy = RBACPolicy()

# Add user
policy.add_user(User(id="user1", name="John", role=Role.ADMIN))

# Check permission
if policy.has_permission("user1", Permission.TASK_CREATE):
    # Allow action
    pass
```

### AuditLogger

```python
from more_core.governance.audit import AuditLogger, AuditRecord

logger = AuditLogger("logs/audit.jsonl")

# Log event
record = logger.log(
    actor="user1",
    action="task:create",
    entity="task_123",
    description="Created new task"
)
```

---

## ZEN Rules

### ZENRulesEnforcer

```python
from more_core.zen_rules import ZENRulesEnforcer, RuleSeverity

enforcer = ZENRulesEnforcer()

# Check violation
is_violation = enforcer.check_violation("ZEN-01", context)

# Register callback for critical rules
enforcer.register_callback(RuleSeverity.P1_CRITICAL, callback_fn)
```

---

## Optimization

### RequestCache

```python
from more_core.optimization import RequestCache, CacheConfig, CacheStrategy

cache = RequestCache(CacheConfig(
    max_size=1000,
    ttl_seconds=3600,
    strategy=CacheStrategy.LRU
))

# Use
cache.set(prompt, model, response)
cached = cache.get(prompt, model)
```

### RateLimiter

```python
from more_core.optimization import RateLimiter

limiter = RateLimiter(rate=10, burst=20)

if await limiter.acquire():
    # Proceed with request
    pass
```

### CircuitBreaker

```python
from more_core.optimization import CircuitBreaker

breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

try:
    result = await breaker.call(llm_function)
except RuntimeError as e:
    # Circuit is open, fast fail
    pass
```

---

## Events

### EventBus

```python
from more_core.core.event_bus import EventBus

bus = EventBus()

# Subscribe
bus.subscribe("task:complete", handler_fn)

# Publish
bus.publish("task:complete", {"task_id": "123"})
```

---

## Streaming (SSE)

### POST /api/v1/tasks/stream

```python
import httpx

async with httpx.AsyncClient(timeout=30) as cli:
    async with cli.stream("POST", "http://localhost:8001/api/v1/tasks/stream",
                           json={"query": "Your prompt"}) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                import json
                event = json.loads(line[6:])
                if "token" in event:
                    print(event["token"], end="", flush=True)
                elif event.get("event") == "done":
                    print(f"\nCompleted: {event['tokens']} tokens")
```

SSE Event types:
- `{"event":"pipeline","layers":[...]}` — 管道信息
- `{"event":"layer_done","layer":"L4","description":"..."}` — 各层完成
- `{"token":"..."}` — L0 token 流
- `{"event":"done","tokens":N,"duration_ms":M}` — 完成

## MCP Server (stdio mode)

```bash
# Codex CLI 集成 (.codex.json)
{
  "mcpServers": {
    "more-os": {
      "command": ".venv/bin/python3",
      "args": ["-m", "more_core.cli", "mcp-serve"]
    }
  }
}

# Claude Code 集成 (.mcp.json)
{
  "mcpServers": {
    "more-os": {
      "command": ".venv/bin/python3",
      "args": ["-m", "more_core.cli", "mcp-serve"]
    }
  }
}
```

### MCP REST API

```python
# List connected MCP servers
GET  /api/v1/mcp/servers

# Connect filesystem MCP server
POST /api/v1/mcp/connect/filesystem?path=/

# Call tool on MCP server
POST /api/v1/mcp/tools/{server_name}/{tool_name}
Body: {"arg": "value"}

# List tools from a server
GET  /api/v1/mcp/tools/{server_name}

# Disconnect
POST /api/v1/mcp/disconnect/{server_name}
```

## A2A Protocol

```python
# Agent Card
GET /a2a/agent-card
→ {"name":"QNMing MoRE OS","skills":["nlp","code_gen",...]}

# Send task (JSON-RPC)
POST /a2a
Body: {
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "task": {
      "messages": [{
        "role": "user",
        "parts": [{"type": "text", "text": "Your task"}]
      }]
    }
  }
}
→ {"result": {"taskId": "...", "status": {"state": "completed"}}}

# List active tasks
GET /a2a/tasks
```

## Error Handling

```python
from more_core.core.errors import (
    MoREError,
    LLMError,
    SandboxError,
    GovernanceError,
    PluginError
)

try:
    result = await core.execute(request)
except LLMError as e:
    # Handle LLM errors
    print(f"LLM error: {e}")
except SandboxError as e:
    # Handle sandbox errors
    print(f"Sandbox error: {e}")
except MoREError as e:
    # Handle general MoRE errors
    print(f"MoRE error: {e}")
```