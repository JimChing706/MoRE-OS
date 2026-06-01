# MoRE OS 使用指南 v0.5.1

> 快速入门指南，5 分钟内完成安装和第一个任务。

---

## 1. 安装

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装 (含 API)
cd more_core && pip install -e ".[api]"
```

## 2. 配置 LLM

编辑 `more_core/.env`：

```bash
# Ollama (推荐，本地免费)
MORE_OLLAMA_ENDPOINT=http://localhost:11434
MORE_OLLAMA_MODEL=qwen2.5:7b

# Provider 优先级
MORE_LLM_FALLBACK_CHAIN=ollama
```

如需 LM Studio：

```bash
MORE_LMSTUDIO_ENDPOINT=http://localhost:1234/v1
MORE_LMSTUDIO_MODEL=qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled
MORE_LLM_FALLBACK_CHAIN=ollama,lmstudio
```

## 3. 启动服务

```bash
# API 服务 (端口 8001)
.venv/bin/python3 -m more_core.cli serve --port 8001

# 前台 Dashboard (端口 3002)
cd app && npm install && npm run dev
```

验证：`curl http://localhost:8001/api/v1/health`

## 4. 第一个任务

```bash
curl -X POST http://localhost:8001/api/v1/tasks/execute \
  -H "Content-Type: application/json" \
  -d '{"query":"用一句话介绍 MoRE OS"}'
```

或 Python SDK：

```python
import asyncio
from more_core import MoRECore, TaskRequest, TaskType

async def main():
    core = MoRECore.from_env()
    await core.start()
    try:
        r = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="介绍一下 MoRE OS"))
        print(r.output)
    finally:
        await core.stop()

asyncio.run(main())
```

## 5. 流式执行 (SSE)

```bash
curl -N -X POST http://localhost:8001/api/v1/tasks/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"Count 1 to 5"}'
```

## 6. MCP Server 模式 (供 Codex/Claude 编排)

```bash
.venv/bin/python3 -m more_core.cli mcp-serve
```

Codex CLI 集成 (`.codex.json`)：

```json
{
  "mcpServers": {
    "more-os": {
      "command": ".venv/bin/python3",
      "args": ["-m", "more_core.cli", "mcp-serve"]
    }
  }
}
```

## 7. 核心 API 速览

| 端点 | 说明 |
|------|------|
| `GET /api/v1/health` | 健康检查 |
| `POST /api/v1/tasks/execute` | 执行任务 |
| `POST /api/v1/tasks/stream` | 流式执行 |
| `GET /api/v1/hands` | 自主 Hands |
| `GET /api/v1/mcp/servers` | MCP 连接 |
| `POST /a2a` | A2A 任务委托 |
| `GET /api/docs` | Swagger UI |

## 8. LLM Provider 配置

### Ollama

```python
from more_core.core.config import LLMProviderConfig

providers = [
    LLMProviderConfig(provider="ollama", name="ollama",
        endpoint="http://localhost:11434", model="qwen2.5:7b", timeout_s=120)
]
```

### LM Studio

```python
LLMProviderConfig(provider="lmstudio", name="lmstudio",
    endpoint="http://localhost:1234/v1", model="local-model", timeout_s=60)
```

### OpenAI 兼容

```python
LLMProviderConfig(provider="openai", name="openai",
    endpoint="https://api.openai.com/v1", model="gpt-4o-mini", api_key="sk-...")
```

## 9. 自定义工具

```python
from more_core.tools.registry import ToolDefinition, ToolResult

async def my_tool(params):
    return ToolResult(tool="my_tool", success=True, output=params.get("input","").upper())

core.tools.register(ToolDefinition(
    name="my_tool", description="Convert to uppercase",
    parameters_schema={"type":"object","properties":{"input":{"type":"string"}}},
    handler=my_tool,
))
```

## 10. 验证脚本

```bash
# 综合试运转
.venv/bin/python3 comprehensive_test.py

# 状态检视
.venv/bin/python3 status_dashboard.py

# 全模块审计
.venv/bin/python3 module_audit.py
```

---

> **版本**：QNMing MoRE OS v0.5.1 · **许可**：Apache-2.0 · **更新**：2026-05-23
