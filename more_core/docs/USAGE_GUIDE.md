# MoRE OS Usage Guide

## Quick Start

### 1. Installation

```bash
# Clone repository
git clone https://github.com/qnming/more-os.git
cd more-os/more_core

# Install dependencies
pip install -e .
```

### 2. Basic Usage

```python
import asyncio
from more_core import MoRECore
from more_core.core.config import Settings
from more_core.core.types import TaskRequest, TaskType

async def main():
    # Configure settings
    settings = Settings(
        providers=[...],  # See LLM Configuration
        fallback_chain=["ollama"],
    )
    
    # Create core
    core = MoRECore(settings)
    
    # Execute task
    request = TaskRequest(
        type=TaskType.NLP_TASK,
        query="What is the capital of France?"
    )
    
    result = await core.execute(request)
    print(result.output)

asyncio.run(main())
```

---

## LLM Configuration

### Ollama

```python
from more_core.core.config import LLMProviderConfig

providers = [
    LLMProviderConfig(
        provider="ollama",
        name="ollama",
        endpoint="http://localhost:11434",
        model="llama2",
        timeout_s=120,
    )
]
```

### LM Studio (Local GPU)

```python
providers = [
    LLMProviderConfig(
        provider="lmstudio",
        name="lmstudio",
        endpoint="http://localhost:1234/v1",
        model="local-model",
        timeout_s=60,
    )
]
```

### DeepSeek API

```python
providers = [
    LLMProviderConfig(
        provider="deepseek",
        name="deepseek",
        endpoint="https://api.deepseek.com",
        model="deepseek-chat",
        api_key="your-api-key",
    )
]
```

---

## Feature Flags

```python
settings = Settings(
    # Enable L2 DGM Evolution
    enable_evolution=True,
    
    # Enable L5 HyperAgent
    enable_metacognition=True,
    
    # Enable L3 Symbolic Engine
    enable_symbolic=True,
)
```

---

## Custom Tools

```python
from more_core.tools.registry import ToolDefinition, ToolRegistry

async def my_tool(params, *, core):
    return ToolResult(
        tool="my_tool",
        success=True,
        output="Result"
    )

registry.register(ToolDefinition(
    name="my_tool",
    description="My custom tool",
    parameters_schema={
        "type": "object",
        "properties": {
            "param": {"type": "string"}
        }
    },
    handler=my_tool
))
```

---

## Security

### RBAC Setup

```python
from more_core.governance.rbac import RBACPolicy, User, Role, Permission

policy = RBACPolicy()

# Add users
policy.add_user(User(id="admin", name="Admin", role=Role.ADMIN))
policy.add_user(User(id="dev", name="Developer", role=Role.DEVELOPER))
policy.add_user(User(id="user", name="User", role=Role.USER))

# Check permissions
policy.check_permission("dev", Permission.TASK_EXECUTE)
```

### Audit Logging

```python
from more_core.governance.audit import AuditLogger

logger = AuditLogger("logs/audit.jsonl")

# Automatic logging for sensitive operations
logger.log(
    actor="user_id",
    action="task:execute",
    entity="task_123",
    metadata={"query": "..."}
)
```

---

## Monitoring

### Metrics

```python
from more_core.metrics import MetricsCollector

collector = MetricsCollector()

# Record metrics
collector.record_request(duration_ms=150.5, success=True)
collector.record_layer("L0", duration_ms=50.0)

# Get snapshot
snapshot = collector.snapshot(cache_hit_rate=0.8, memory_mb=256.0)
```

### Health Check

```python
# Check provider health
health_status = await llm_manager.health()

# Result: {"ollama": True, "lmstudio": False}
```

---

## Error Handling

```python
from more_core.core.errors import MoREError, LLMError

try:
    result = await core.execute(request)
except LLMError as e:
    # All providers failed
    print(f"LLM error: {e}")
except MoREError as e:
    # General error
    print(f"MoRE error: {e}")
```

---

## Performance Tuning

### Caching

```python
from more_core.optimization import RequestCache, CacheConfig, CacheStrategy

cache = RequestCache(CacheConfig(
    max_size=1000,
    ttl_seconds=3600,
    strategy=CacheStrategy.LRU
))
```

### Rate Limiting

```python
from more_core.optimization import RateLimiter

limiter = RateLimiter(rate=10, burst=20)

if await limiter.acquire():
    # Process request
    pass
```

### Circuit Breaker

```python
from more_core.optimization import CircuitBreaker

breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=30
)
```

---

## Configuration Reference

### Settings

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `plugin_dir` | str | "plugins" | Plugin directory |
| `log_dir` | str | "logs" | Log directory |
| `providers` | list[LLMProviderConfig] | [] | LLM providers |
| `fallback_chain` | list[str] | [] | Provider fallback order |
| `enable_evolution` | bool | False | Enable L2 DGM |
| `enable_metacognition` | bool | False | Enable L5 HyperAgent |
| `enable_symbolic` | bool | True | Enable L3 Symbolic |
| `sandbox_timeout_s` | int | 20 | Sandbox timeout |
| `sandbox_memory_mb` | int | 512 | Sandbox memory limit |

### TaskType

- `NLP_TASK` - General NLP queries
- `CODE_GENERATION` - Code generation
- `CODE_DEBUGGING` - Code debugging
- `CODE_REVIEW` - Code review
- `DATA_ANALYSIS` - Data analysis
- `RESEARCH` - Research tasks

---

## Troubleshooting

### Provider Connection Issues

1. Check provider is running
2. Verify endpoint URL
3. Check API key (if required)
4. Increase timeout for slow providers

### Performance Issues

1. Enable caching
2. Configure rate limiting
3. Use circuit breaker
4. Monitor metrics

### Security Issues

1. Review audit logs
2. Check RBAC permissions
3. Monitor ZEN rules violations
4. Review incident responses