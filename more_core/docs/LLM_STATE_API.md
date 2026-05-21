# LLM调用状态管理API文档

**版本**: 0.3.0  
**更新时间**: 2026-05-06

---

## 概述

提供动态调整LLM调用参数的能力,支持实时修改temperature、max_tokens、provider等参数,并提供使用统计和历史记录。

---

## API端点

### 1. 获取完整状态

**GET** `/api/v1/llm/state`

返回当前LLM调用状态的完整信息,包括当前参数、使用统计、提供商信息。

**响应示例**:
```json
{
  "current_state": {
    "provider": "ollama",
    "model": "qwen2.5:7b",
    "temperature": 0.7,
    "max_tokens": 2048,
    "top_p": 0.9,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "timeout_s": 120,
    "retry_count": 3,
    "fallback_enabled": true,
    "cache_enabled": true,
    "streaming_enabled": false
  },
  "usage": {
    "total_requests": 0,
    "total_tokens": 0,
    "total_cost": 0.0,
    "provider_usage": {},
    "avg_latency_ms": 0.0
  },
  "available_providers": [...]
}
```

---

### 2. 获取当前参数

**GET** `/api/v1/llm/state/current`

返回当前LLM调用的核心参数。

**响应示例**:
```json
{
  "provider": "ollama",
  "model": "qwen2.5:7b",
  "temperature": 0.7,
  "max_tokens": 2048,
  "top_p": 0.9,
  "frequency_penalty": 0.0,
  "presence_penalty": 0.0,
  "timeout_s": 120,
  "retry_count": 3,
  "fallback_enabled": true,
  "cache_enabled": true,
  "streaming_enabled": false
}
```

---

### 3. 动态更新参数

**POST** `/api/v1/llm/state/update`

动态调整LLM调用参数。

**请求体**:
```json
{
  "provider": "deepseek",
  "model": "deepseek-chat",
  "temperature": 0.9,
  "max_tokens": 4096,
  "top_p": 0.95,
  "frequency_penalty": 0.5,
  "presence_penalty": 0.5,
  "timeout_s": 60,
  "retry_count": 5,
  "fallback_enabled": true,
  "cache_enabled": false,
  "streaming_enabled": true
}
```

**响应示例**:
```json
{
  "success": true,
  "updated": {
    "temperature": 0.9,
    "max_tokens": 4096
  },
  "current_state": {...}
}
```

**参数说明**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| provider | string | "lmstudio" | LLM提供商 |
| model | string | "local-model" | 模型名称 |
| temperature | float | 0.7 | 采样温度 (0-2) |
| max_tokens | int | 2048 | 最大输出tokens |
| top_p | float | 0.9 | nucleus采样 |
| frequency_penalty | float | 0.0 | 频率惩罚 |
| presence_penalty | float | 0.0 | 存在惩罚 |
| timeout_s | int | 120 | 超时秒数 |
| retry_count | int | 3 | 重试次数 |
| fallback_enabled | bool | true | 启用fallback |
| cache_enabled | bool | true | 启用缓存 |
| streaming_enabled | bool | false | 启用流式 |

**LM Studio 专用参数** (当provider="lmstudio"时):

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| lmstudio_endpoint | string | "http://localhost:1234/v1" | LM Studio API端点 |
| lmstudio_context_length | int | 32768 | 最大上下文长度 |
| lmstudio_gpu_layers | int | -1 | GPU加速层数 (-1=自动) |
| lmstudio_threads | int | 0 | CPU线程数 (0=自动) |
| lmstudio_vram_fraction | float | 0.8 | VRAM使用比例 (0.0-1.0) |

---

### 4. 重置状态

**POST** `/api/v1/llm/state/reset`

将LLM状态重置为默认值。

**响应示例**:
```json
{
  "success": true,
  "reset_to": {
    "provider": "ollama",
    "model": "qwen2.5:7b",
    "temperature": 0.7,
    "max_tokens": 2048,
    ...
  }
}
```

---

### 5. 使用统计

**GET** `/api/v1/llm/usage`

返回LLM使用统计信息。

**响应示例**:
```json
{
  "total_requests": 1250,
  "total_tokens": 560000,
  "total_cost": 8.50,
  "provider_usage": {
    "ollama": 200000,
    "deepseek": 360000
  },
  "avg_latency_ms": 450.5
}
```

---

### 6. 提供商信息

**GET** `/api/v1/llm/providers`

返回可用LLM提供商的信息。

**响应示例**:
```json
{
  "providers": [
    {
      "name": "lmstudio",
      "type": "local",
      "cost_per_1k": 0.0,
      "avg_latency_ms": 150,
      "recommended_for": ["high_quality_local", "development"],
      "description": "LM Studio - 本地模型运行器,支持多种开源模型",
      "endpoint": "http://localhost:1234/v1",
      "supports_streaming": true,
      "supports_vision": true,
      "config_options": {
        "context_length": "最大上下文长度 (默认32768)",
        "gpu_layers": "GPU加速层数 (-1=自动)",
        "threads": "CPU线程数 (0=自动)",
        "vram_fraction": "VRAM使用比例 (0.0-1.0)"
      }
    },
    {
      "name": "ollama",
      "type": "local",
      "cost_per_1k": 0.0,
      "avg_latency_ms": 100,
      "recommended_for": ["simple_tasks", "development"]
    },
    {
      "name": "deepseek",
      "type": "api",
      "cost_per_1k": 0.014,
      "avg_latency_ms": 500,
      "recommended_for": ["code_generation", "reasoning"]
    },
    ...
  ]
}
```

---

### 7. 状态历史

**GET** `/api/v1/llm/history?limit=10`

返回LLM状态变更的历史记录。

**响应示例**:
```json
{
  "history": [
    {
      "timestamp": 1714992000.0,
      "changes": {"temperature": 0.9},
      "state": {...}
    },
    ...
  ]
}
```

---

## 使用示例

### cURL

```bash
# 获取当前状态
curl http://localhost:8000/api/v1/llm/state/current

# 更新参数
curl -X POST http://localhost:8000/api/v1/llm/state/update \
  -H "Content-Type: application/json" \
  -d '{"temperature": 0.8, "max_tokens": 4096}'

# 获取使用统计
curl http://localhost:8000/api/v1/llm/usage
```

### Python

```python
import requests

# 更新LLM参数
response = requests.post(
    "http://localhost:8000/api/v1/llm/state/update",
    json={"temperature": 0.9, "provider": "deepseek"}
)
print(response.json())

# 获取使用统计
response = requests.get("http://localhost:8000/api/v1/llm/usage")
print(response.json())
```

---

## 注意事项

1. **参数验证**: 部分参数有有效范围限制 (如temperature: 0-2)
2. **持久化**: 当前状态存储在内存中,重启后重置
3. **线程安全**: 状态管理器是线程安全的,支持并发访问
4. **回调机制**: 支持注册回调函数,状态变更时自动通知

---

*文档生成时间: 2026-05-06*