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