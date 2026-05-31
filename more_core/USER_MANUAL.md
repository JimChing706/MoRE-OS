# QNMing MoRE OS v0.5.1 — 用户手册

> **QNMing MoRE OS** 是一个领域无关的神经-符号元认知自进化 Agent 操作系统内核。
> 本手册基于实际代码（2026-05-23 审计后版本）编写，覆盖安装、配置、核心概念、
> API 参考、插件开发、运维与故障排查。

---

## 目录

1. [快速入门](#1-快速入门)
2. [核心概念与架构](#2-核心概念与架构)
3. [配置参考](#3-配置参考)
4. [CLI 命令行](#4-cli-命令行)
5. [Python SDK](#5-python-sdk)
6. [REST API](#6-rest-api)
7. [六层处理管道](#7-六层处理管道)
8. [LLM 多 Provider 管理](#8-llm-多-provider-管理)
9. [工具系统](#9-工具系统)
10. [记忆系统](#10-记忆系统)
11. [符号推理与治理](#11-符号推理与治理)
12. [进化引擎 (DGM)](#12-进化引擎-dgm)
13. [元认知与自修改](#13-元认知与自修改)
14. [沙箱执行](#14-沙箱执行)
15. [插件开发](#15-插件开发)
16. [事件总线](#16-事件总线)
17. [服务注册](#17-服务注册)
18. [审计日志](#18-审计日志)
19. [安全机制](#19-安全机制)
20. [故障排查](#20-故障排查)
21. [Hands 系统](#21-hands-系统)
22. [ZEN 零信任规则](#22-zen-零信任规则)
23. [安全层总览](#23-安全层总览)
24. [CJK/国际化支持](#24-cjk国际化支持)
25. [附录：环境变量速查表](#25-附录环境变量速查表)

---

## 1. 快速入门

### 1.1 安装

```bash
# 基础安装（不含 HTTP API）
pip install -e .

# 含 FastAPI HTTP 服务
pip install -e ".[api]"

# 开发模式（含测试框架）
pip install -e ".[dev]"
```

### 1.2 最小运行：CLI 单次任务

```bash
# 设置 LLM Provider（以 Ollama 为例）
export MORE_OLLAMA_ENDPOINT=http://localhost:11434
export MORE_OLLAMA_MODEL=qwen2.5:7b

# 执行一个 NLP 任务
more-os run --type nlp_task --query "用 Python 实现快速排序"
```

输出为 JSON 格式的 `TaskResult`，包含 `output`（LLM 回复）、`reasoning_chain`（推理链路）、`performance`（耗时与 token 统计）。

### 1.3 启动 HTTP API 服务

```bash
more-os serve --host 0.0.0.0 --port 8001
```

访问 `http://localhost:8001/docs` 查看自动生成的 OpenAPI 文档。

### 1.4 Python 编程方式

```python
import asyncio
from more_core import MoRECore, TaskRequest, TaskType

async def main():
    core = MoRECore.from_env()
    await core.start()
    try:
        result = await core.execute(
            TaskRequest(type=TaskType.CODE_GENERATION, query="写一个快速排序")
        )
        print(result.output)
    finally:
        await core.stop()

asyncio.run(main())
```

---

## 2. 核心概念与架构

### 2.1 设计原则

| 编号 | 原则 | 说明 |
|------|------|------|
| G1 | 领域无关内核 + 行业插件壳 | Core 不含任何特定行业代码；行业逻辑通过 Plugin 接入 |
| G2 | 分层可替换 | 每个 Layer 是 Protocol 接口 + 基线实现，插件可整体替换 |
| G3 | 本地优先、Provider 中立 | LLM Manager 支持多 Provider + 自动 fallback |
| G4 | 受控自进化 | L2 DGM、L5 HyperAgent 默认关闭，需显式启用 + 审计 |
| G5 | 本体治理与审计 | 基于 AOW v1.0 实体映射的完整审计链路 |
| G6 | 插件接口稳定 | PluginInterface 向下兼容至少 12 个月 |

### 2.2 系统架构总览

```
                ┌─────────────────────────────────────────┐
                │       runtime.MoRECore (Orchestrator)    │
                └────────────────────┬────────────────────┘
                                     │ execute(TaskRequest)
                                     ▼
                 ┌──────────────────────────────────┐
                 │       router.LayerRouter          │  难度感知路由
                 └──────┬──────────────┬────────────┘
                        │              │
    ┌───────────────────┼──────────────┼───────────────────┐
    ▼                   ▼              ▼                    ▼
 L5 元认知          L4 认知        L3 符号推理          L2 进化
 Calibrator /      任务解析 /     本体 + 规则引擎      DGM 归档 /
 HyperAgent*       难度评估                            变异评估*
    │                   │              │                    │
    └───────┬───────────┴──────────────┴────────┬──────────┘
            ▼                                    ▼
       L1 编排 (Agent 路由 / 协作决策)
                        │
                        ▼
                   L0 执行层
          (LLM 生成 → 工具调用 → 沙箱执行)

  * L2/L5 默认关闭；开启需设置 enable_evolution / enable_metacognition
```

### 2.3 核心数据流

```
TaskRequest  →  PolicyEnforcer.check()  →  LayerRouter.route()
             →  L4 (解析/规划)  →  L3 (规则引擎)  →  L1 (编排)
             →  L0 (LLM + 工具)  →  TaskResult
```

每层通过 `LayerContext` 共享状态（`scratch` 字典）。`accumulated_steps` 记录推理链路，最终汇入 `TaskResult.reasoning_chain`。

### 2.4 目录结构

```
more_core/
├── core/              # 类型、错误、配置、服务注册、事件总线
│   ├── types.py       # TaskRequest, TaskResult, LayerId, TaskType ...
│   ├── config.py      # Settings, LLMProviderConfig
│   ├── errors.py      # MoREError 异常层次
│   ├── event_bus.py   # 异步发布-订阅
│   └── service_registry.py
├── llm/               # LLM Manager + Provider 实现
│   ├── provider.py    # LLMRequest, LLMResponse, LLMProvider (Protocol)
│   ├── manager.py     # LLMManager: fallback + 缓存
│   └── providers/     # ollama.py, lmstudio.py, openai_compat.py
├── tools/             # 工具注册与内置工具
│   ├── registry.py    # ToolRegistry, ToolDefinition, ToolResult
│   └── builtins.py    # python_exec, shell_exec, memory_search, memory_store
├── plugins/           # 插件系统
│   ├── interface.py   # PluginInterface (Protocol), PluginMetadata, PluginContext
│   ├── manager.py     # PluginManager: 发现 / 加载 / 激活 / 停用
│   └── sdk.py         # PluginBase 基类 + scaffold_plugin 脚手架
├── sandbox/           # 沙箱执行
│   ├── subprocess_sandbox.py  # 基线沙箱 (超时 + 内存限制)
│   └── linux_sandbox.py       # Linux cgroup v2 硬化沙箱
├── layers/            # L0–L5 层实现
│   ├── base.py        # Layer (ABC), LayerContext, LayerResult
│   ├── l0_execution.py
│   ├── l1_orchestration.py
│   ├── l2_evolution.py
│   ├── l3_symbolic.py
│   ├── l4_cognition.py
│   └── l5_metacognition.py
├── router/            # 管道路由
│   └── layer_router.py  # LayerRouter, DEFAULT_PIPELINES, RoutingDecision
├── memory/            # 三路记忆
│   ├── store.py       # MemoryStore (内存版)
│   └── sqlite_store.py # SQLiteMemoryStore (持久化)
├── ontology/          # 本体 + 规则引擎
│   ├── aow.py         # AOW 实体与约束模型
│   ├── engine.py      # OntologyEngine
│   └── rule_engine.py # RuleEngine (前向链)
├── evolution/         # 进化引擎
│   ├── archive.py     # EvolutionArchive
│   ├── sqlite_archive.py
│   ├── dgm.py         # DGMEngine
│   └── benchmark.py   # BenchmarkRunner, Benchmark, BenchmarkReport
├── metacognition/     # 元认知
│   ├── calibrator.py  # Calibrator (置信度-准确度校准)
│   ├── hyperagent.py  # HyperAgent (受控自修改)
│   └── metacognition.py # MetacognitionService (门面)
├── governance/        # 治理
│   ├── audit.py       # AuditLogger (JSONL)
│   └── policy.py      # PolicyEnforcer, GovernanceWorkflow
├── runtime/           # 运行时
│   └── orchestrator.py # MoRECore (组合根)
├── api/               # HTTP API (可选)
│   └── server.py      # FastAPI 应用工厂
├── cli.py             # 命令行入口
└── version.py         # 版本号
```

---

## 3. 配置参考

### 3.1 Settings 模型

所有配置通过 `Settings` Pydantic 模型管理，可由环境变量或代码构造：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `plugin_dir` | `str` | `"plugins"` | 插件目录路径 |
| `log_dir` | `str` | `"logs"` | 日志目录 |
| `providers` | `list[LLMProviderConfig]` | `[]` | LLM Provider 列表 |
| `fallback_chain` | `list[str]` | `[]` | Provider fallback 顺序 |
| `enable_evolution` | `bool` | `False` | L2 DGM 进化开关 |
| `enable_metacognition` | `bool` | `False` | L5 自修改开关 |
| `enable_symbolic` | `bool` | `True` | L3 符号推理开关 |
| `custom_pipelines` | `dict[str, list[str]] \| None` | `None` | 自定义管道模板覆盖 |
| `strict_ontology` | `bool` | `True` | 违规时是否阻断任务 |
| `audit_log_path` | `str` | `"logs/audit.jsonl"` | 审计日志路径 |
| `sandbox_timeout_s` | `int` | `20` | 沙箱超时（秒） |
| `sandbox_memory_mb` | `int` | `512` | 沙箱内存限制（MB） |

### 3.2 LLMProviderConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | — | Provider 唯一名称 |
| `provider` | `str` | — | 类型：`ollama` / `lmstudio` / `openai` / `anthropic` / `custom` |
| `endpoint` | `str` | — | API 端点 URL |
| `model` | `str` | — | 模型名称 |
| `api_key` | `str \| None` | `None` | API Key（openai/anthropic/custom 需要） |
| `max_tokens` | `int` | `4096` | 最大生成 token 数 |
| `temperature` | `float` | `0.7` | 采样温度 |
| `timeout_s` | `int` | `120` | 单次请求超时 |

### 3.3 环境变量驱动配置

`Settings.from_env()` 方法从环境变量自动构造配置（`MoRECore.from_env()` 内部调用）。详见 [附录](#21-附录环境变量速查表)。

---

## 4. CLI 命令行

入口：`more-os`（或 `python -m more_core`）

### 4.1 `more-os serve` — 启动 HTTP API

```bash
more-os serve [--host HOST] [--port PORT]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `8001` | 监听端口 |

使用 Uvicorn 运行 FastAPI 应用，自动完成 `core.start()` / `core.stop()` 生命周期。

### 4.2 `more-os mcp-serve` — MCP stdio 服务 (v0.5.1)

```bash
more-os mcp-serve
```

启动 MCP Server 在 stdio 模式，供 Codex CLI / Claude Code 通过 MCP 协议调用 MoRE OS 工具。

### 4.3 `more-os run` — 执行单次任务

```bash
more-os run --type TASK_TYPE --query "你的问题"
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--type` | `nlp_task` | 任务类型（见 TaskType 枚举，小写） |
| `--query` / `-q` | 必填 | 任务内容 |

**支持的 `--type` 值**：

| 类型 | 值 | 典型用途 |
|------|-----|---------|
| 自然语言 | `nlp_task` | 对话、问答、翻译、摘要 |
| 代码生成 | `code_generation` | 生成代码并在沙箱执行 |
| 代码调试 | `code_debugging` | 分析和修复代码问题 |
| 代码审查 | `code_review` | 代码质量分析 |
| 数学推理 | `math_reasoning` | 数学问题求解 |
| 数据分析 | `data_analysis` | 数据处理与分析 |
| 多 Agent | `multi_agent_orchestration` | 多 Agent 协作 |
| 架构设计 | `architecture_design` | 系统架构规划 |
| 自改进 | `self_improvement` | 系统自进化（需启用 gate） |
| 跨域迁移 | `cross_domain_transfer` | 跨领域知识迁移 |
| 插件定义 | `plugin_defined` | 插件自定义任务类型 |

---

## 5. Python SDK

### 5.1 核心入口

```python
from more_core import MoRECore, TaskRequest, TaskType, TaskResult
```

### 5.2 生命周期

```python
core = MoRECore.from_env()      # 从环境变量构造
# 或者
core = MoRECore(settings)       # 从 Settings 对象构造

await core.start()               # 启动事件总线、注册内置工具、发现插件
result = await core.execute(req) # 执行任务
await core.stop()                # 优雅关闭：停用插件 → 停止事件总线 → 关闭持久化
```

### 5.3 TaskRequest 字段

```python
req = TaskRequest(
    type=TaskType.CODE_GENERATION,   # 任务类型
    query="实现二分查找",              # 必填：任务内容
    context={"temperature": 0.5},     # 可选：传递给 LLM 的参数
    target_layer=LayerId.L0,          # 可选：指定目标层，绕过路由
    require_metacognitive_monitoring=True,  # 可选：强制包含 L5
    allow_self_improvement=False,     # 可选：允许 L2/L5 自修改
    timeout_s=60.0,                   # 可选：任务超时（1~600 秒）
)
```

### 5.4 TaskResult 结构

```python
result.task_id           # "task_a1b2c3d4e5f6"
result.status            # TaskStatus.SUCCESS / FAILED / REJECTED / PARTIAL
result.output            # LLM 生成的最终文本输出
result.reasoning_chain   # list[ReasoningStep] — 每层的推理步骤
result.performance       # PerformanceMetrics — 耗时 / token / 层转换数
result.calibration       # dict — 元认知校准报告（L5 启用时）
result.evolution_branch  # str — 进化分支名称（L2 启用时）
result.metadata          # dict — 附加元数据
```

### 5.5 ReasoningStep 结构

每个推理步骤记录一层的处理结果：

```python
step.id               # 步骤序号（从 1 开始）
step.layer             # LayerId（L0~L5）
step.description       # 人类可读描述
step.duration_ms       # 该层处理耗时（毫秒）
step.input_tokens      # 输入 token 数
step.output_tokens     # 输出 token 数
step.confidence        # 该层输出置信度（0.0~1.0）
step.timestamp         # Unix 时间戳
```

### 5.6 错误处理

```python
from more_core import MoREError, LLMError, SandboxError, GovernanceError, PluginError

try:
    result = await core.execute(req)
except GovernanceError:
    # 任务被治理策略拒绝（status=REJECTED）
    pass
except LLMError:
    # 所有 LLM Provider 均失败
    pass
except SandboxError:
    # 沙箱执行异常
    pass
```

注意：`execute()` 方法内部已捕获异常并映射到 `TaskStatus`，不会向调用方抛出。上述 except 适用于直接调用底层子系统的场景。

---

## 6. REST API

需要安装 `pip install -e ".[api]"`。所有端点前缀为 `/api/v1`。

### 6.1 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/health` | 健康检查 + 版本 + 功能开关状态 |
| `GET` | `/api/v1/system/state` | 系统状态：注册表、进化归档、记忆、活跃插件 |
| `POST` | `/api/v1/tasks/execute` | 执行任务（核心端点） |
| `GET` | `/api/v1/tasks/{task_id}/status` | 获取任务执行状态 |
| `POST` | `/api/v1/tasks/{task_id}/execute` | 执行待处理任务 |
| `GET` | `/api/v1/tasks/history` | 获取任务执行历史 |
| `GET` | `/api/v1/plugins` | 插件列表（已发现 + 已激活） |
| `GET` | `/api/v1/llm/health` | LLM Provider 健康状态 |
| `GET` | `/api/v1/llm/state` | LLM 调用状态和统计 |
| `GET` | `/api/v1/llm/state/current` | 当前 LLM 参数 |
| `POST` | `/api/v1/llm/state/update` | 动态更新 LLM 参数 |
| `POST` | `/api/v1/llm/state/reset` | 重置 LLM 状态 |
| `GET` | `/api/v1/llm/usage` | LLM 使用统计 |
| `GET` | `/api/v1/llm/providers` | 可用 LLM Provider 信息 |
| `GET` | `/api/v1/llm/history` | LLM 状态变更历史 |
| `GET` | `/api/v1/llm/reasoning` | Reasoning Router 状态 |
| `POST` | `/api/v1/llm/reasoning/config` | 更新 Reasoning Router 配置 |
| `GET` | `/api/v1/llm/reasoning/check` | 检查模型是否支持推理 |
| `GET` | `/api/v1/llm/aliases` | 模型别名列表 |
| `GET` | `/api/v1/llm/aliases/resolve/{alias}` | 解析模型别名 |
| `GET` | `/api/v1/zen/rules` | 获取所有 ZEN 规则 |
| `GET` | `/api/v1/zen/compliance` | ZEN 规则合规报告 |
| `GET` | `/api/v1/zen/violations` | ZEN 规则违规记录 |
| `POST` | `/api/v1/zen/violations/{violation_id}/resolve` | 解决 ZEN 规则违规 |
| `GET` | `/api/v1/ontology/constraints` | 本体约束列表 |
| `GET` | `/api/v1/evolution/archive` | 进化归档统计 |
| `GET` | `/api/v1/incidents` | 主动事件列表 |
| `POST` | `/api/v1/incidents/{incident_id}/resolve` | 解决主动事件 |
| `POST` | `/api/v1/requirements/parse` | 解析 Markdown 需求文档 |
| `POST` | `/api/v1/requirements/import` | 导入需求并创建任务 |
| `GET` | `/api/v1/requirements/templates` | 获取需求文档模板 |
| `POST` | `/api/v1/requirements/validate` | 验证需求文档 |
| `GET` | `/api/v1/hands` | 所有注册/活跃 Hands |
| `GET` | `/api/v1/hands/registry` | Hand 清单列表 |
| `POST` | `/api/v1/hands/{hand_id}/activate` | 激活 Hand |
| `POST` | `/api/v1/hands/{hand_id}/deactivate` | 停用 Hand |
| `POST` | `/api/v1/hands/{hand_id}/pause` | 暂停 Hand |
| `POST` | `/api/v1/hands/{hand_id}/resume` | 恢复 Hand |
| `POST` | `/api/v1/hands/{hand_id}/run` | 手动触发 Hand 执行 |
| `GET` | `/api/v1/hands/{hand_id}/status` | Hand 状态 |
| `GET` | `/api/v1/hands/{hand_id}/results` | Hand 执行结果 |
| `POST` | `/api/v1/hands/{hand_id}/save` | 保存 Hand 状态 |
| `POST` | `/api/v1/hands/{hand_id}/wakeup` | 唤醒已保存的 Hand |
| `POST` | `/api/v1/hands/{hand_id}/clone` | 克隆 Hand |
| `GET` | `/api/v1/hands/saved` | 已保存的 Hands 列表 |
| `GET` | `/api/v1/channels` | 消息通道列表 |
| `GET` | `/api/v1/channels/status` | 通道状态 |
| `GET` | `/api/v1/channels/reconnect` | 重连状态 |
| `GET` | `/api/v1/channels/reconnect/states` | 重连状态详情 |
| `GET` | `/api/v1/schedules` | 调度任务列表 |
| `POST` | `/api/v1/schedules/{job_id}/run` | 执行调度任务 |
| `POST` | `/api/v1/schedules/{job_id}/enable` | 启用调度任务 |
| `POST` | `/api/v1/schedules/{job_id}/disable` | 停用调度任务 |
| `GET` | `/api/v1/skills` | 技能列表 |
| `POST` | `/api/v1/skills/{skill_id}/run` | 执行技能 |
| `GET` | `/api/v1/commands` | 命令列表 |
| `GET` | `/api/v1/commands/stats` | 命令统计 |
| `GET` | `/api/v1/security/status` | 安全层总览 |
| `GET` | `/api/v1/security/rbac/roles` | RBAC 角色列表 |
| `POST` | `/api/v1/security/rbac/assign` | 分配 RBAC 角色 |
| `GET` | `/api/v1/security/taint` | 污染追踪状态 |
| `GET` | `/api/v1/security/taint/violations` | 污染违规记录 |
| `GET` | `/api/v1/security/output-filter/stats` | 输出过滤统计 |
| `POST` | `/api/v1/security/output-filter/scan` | 扫描文本安全 |
| `POST` | `/api/v1/reload/{scope}` | 热重载子系统 |
| `POST` | `/api/v1/reload` | 重载所有子系统 |
| `GET` | `/api/v1/monitor/dashboard` | 仪表板快照 |
| `GET` | `/api/v1/monitor/health` | 完整健康检查 |

### 6.2 POST /api/v1/tasks/execute

**请求体**：

```json
{
  "type": "code_generation",
  "query": "写一个快速排序",
  "context": {},
  "require_metacognitive_monitoring": false,
  "allow_self_improvement": false,
  "target_layer": null,
  "timeout_s": 60.0
}
```

**响应**：

```json
{
  "task_id": "task_a1b2c3d4e5f6",
  "layer": "L0",
  "status": "success",
  "output": "...",
  "reasoning_chain": [...],
  "performance": {
    "total_duration_ms": 1234.5,
    "tokens_used": 567,
    "layer_transitions": 3
  },
  "calibration": null,
  "evolution_branch": null,
  "metadata": {}
}
```

### 6.3 CORS 配置

默认仅允许 `http://localhost:3000` 和 `http://127.0.0.1:3000`。

通过环境变量自定义：

```bash
export MORE_CORS_ORIGINS="https://app.example.com,https://admin.example.com"
```

允许的 HTTP 方法：`GET`, `POST`。允许的请求头：`Authorization`, `Content-Type`。

---

## 6.5 流式任务执行 (SSE) — v0.5.1 新增

`POST /api/v1/tasks/stream` 通过 Server-Sent Events 实时推送 token：

```bash
curl -N -X POST http://localhost:8001/api/v1/tasks/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"Count from 1 to 5"}'
```

SSE 事件格式：
```
data: {"event":"pipeline","layers":["L4","L3","L1","L0"],"task_id":"task_xxx"}
data: {"event":"layer_done","layer":"L4",...}
data: {"token":"1"}
data: {"token":"\n"}
data: {"token":"2"}
...
data: {"event":"done","tokens":15,"duration_ms":8234.5}
```

客户端示例 (Python httpx)：
```python
import httpx, json

async with httpx.AsyncClient(timeout=30) as cli:
    async with cli.stream("POST", "http://localhost:8001/api/v1/tasks/stream",
                           json={"query": "Hello"}) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                event = json.loads(line[6:])
                if "token" in event:
                    print(event["token"], end="", flush=True)
```

## 6.6 MCP Server & Client — v0.5.1 新增

### MCP Server (stdio mode)

暴露 MoRE OS 全部 29 个工具给 Codex CLI / Claude Code：

```bash
# 启动 MCP stdio server
.venv/bin/python3 -m more_core.cli mcp-serve
```

Codex CLI 集成配置 (`.codex.json`)：
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

### MCP REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/mcp/servers` | 已连接的 MCP Server 列表 |
| `POST` | `/api/v1/mcp/connect/filesystem?path=/` | 连接 npx MCP filesystem |
| `POST` | `/api/v1/mcp/tools/{server}/{tool}` | 调用远程工具 |
| `POST` | `/api/v1/mcp/disconnect/{server}` | 断开连接 |

## 6.7 A2A Agent-to-Agent — v0.5.1 新增

MoRE OS 支持 Google A2A 协议，可接收来自其他 Agent 的任务委托：

| 端点 | 说明 |
|------|------|
| `POST /a2a` | JSON-RPC 端点 (tasks/send, tasks/get, agent/card) |
| `GET /a2a/agent-card` | Agent 能力卡片 |
| `GET /a2a/tasks` | 活跃任务列表 |

```bash
# 发送任务
curl -X POST http://localhost:8001/a2a \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tasks/send","params":{"task":{"messages":[{"role":"user","parts":[{"text":"Say hi"}]}]}}}'
# → {"result":{"taskId":"...","status":{"state":"completed"}}}
```

---

## 7. 六层处理管道

### 7.1 层定义

| 层 | ID | 名称 | 职责 | 默认启用 |
|----|----|------|------|---------|
| L5 | `LayerId.L5` | 元认知层 | 置信度校准 + HyperAgent 自修改 | 需显式启用 |
| L4 | `LayerId.L4` | 认知层 | 任务解析、难度评估、规划 | ✅ 始终 |
| L3 | `LayerId.L3` | 符号推理层 | 本体检查 + 前向链规则引擎 | ✅ 默认启用 |
| L2 | `LayerId.L2` | 进化层 | DGM 变异 → 评估 → 归档 | 需显式启用 |
| L1 | `LayerId.L1` | 编排层 | 难度-能力路由、Agent 协作决策 | ✅ 始终 |
| L0 | `LayerId.L0` | 执行层 | LLM 生成 → 工具调用 → 沙箱执行 | ✅ 始终 |

### 7.2 管道路由规则

`LayerRouter` 根据 `TaskType` 选择管道模板：

| TaskType | 默认管道 |
|----------|---------|
| `nlp_task` | L4 → L3 → L1 → L0 |
| `code_generation` | L4 → L3 → L1 → L0 |
| `code_debugging` | L4 → L3 → L1 → L0 |
| `code_review` | L4 → L3 → L1 → L0 |
| `data_analysis` | L4 → L3 → L1 → L0 |
| `math_reasoning` | L4 → L3 → L1 → L0 |
| `self_improvement` | L5 → L2 → L1 → L0 |
| `architecture_design` | L5 → L4 → L3 → L1 → L0 |
| `cross_domain_transfer` | L5 → L4 → L1 → L0 |
| `multi_agent_orchestration` | L4 → L1 → L0 |
| `plugin_defined` | L4 → L1 → L0 |

**功能门控**：即使管道模板包含某层，若对应开关关闭，该层会被移除：

- `enable_symbolic=False` → 移除 L3
- `enable_evolution=False` → 移除 L2
- `enable_metacognition=False` → 移除 L5（除非 `require_metacognitive_monitoring=True`）

### 7.3 自定义管道

**方式 1：Settings 配置**

```python
settings = Settings(
    custom_pipelines={
        "nlp_task": ["L4", "L0"],          # 跳过 L3 和 L1
        "data_analysis": ["L4", "L3", "L0"],
    }
)
```

**方式 2：插件运行时注册**

```python
# 在插件 activate() 中
core.router.register_pipeline(
    TaskType.PLUGIN_DEFINED,
    [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0],
)
```

**方式 3：指定 target_layer 直接路由**

```python
req = TaskRequest(query="hello", target_layer=LayerId.L0)
# 生成管道：L4 → L0（从 L4 到目标层的传递闭包）
```

### 7.4 管道查询

```python
pipelines = core.router.list_pipelines()
# {"nlp_task": ["L4", "L3", "L1", "L0"], ...}
```

---

## 8. LLM 多 Provider 管理

### 8.1 支持的 Provider

| Provider | 类 | 说明 |
|----------|-----|------|
| Ollama | `OllamaProvider` | 本地部署，使用 `/api/generate` |
| LMStudio | `LMStudioProvider` | 本地 OpenAI-兼容 API |
| OpenAI / 兼容 | `OpenAICompatProvider` | 支持 OpenAI、DeepSeek、Kimi、智谱等 |

### 8.2 Fallback 链

当主 Provider 失败时，自动尝试下一个：

```bash
# 配置三个 Provider，按顺序 fallback
export MORE_OLLAMA_ENDPOINT=http://localhost:11434
export MORE_OLLAMA_MODEL=qwen2.5:7b

export MORE_OPENAI_API_KEY=sk-...
export MORE_OPENAI_MODEL=gpt-4o-mini

export MORE_LLM_FALLBACK_CHAIN=ollama,openai
```

不指定 `MORE_LLM_FALLBACK_CHAIN` 时，按 Provider 注册顺序（Ollama → LMStudio → OpenAI）自动构成链。

### 8.3 缓存机制

`LLMManager` 内置 LRU 缓存（容量 256 条）。缓存 key 包含：

- Provider 名称
- system prompt
- prompt 内容
- temperature
- max_tokens
- stop 序列
- extra 参数（排序后）

相同请求直接返回缓存结果（`latency_ms=0`，`cached=True`）。

通过 `use_cache=False` 可绕过缓存：

```python
resp = await core.llm.generate(req, use_cache=False)
```

### 8.4 指定 Provider

```python
resp = await core.llm.generate(req, provider="ollama")
```

### 8.5 健康检查

```python
health = await core.llm.health()
# {"ollama": True, "openai": False}
```

---

## 9. 工具系统

### 9.1 内置工具

| 工具名 | 说明 | 需要沙箱 |
|--------|------|---------|
| `python_exec` | 在沙箱中执行 Python 代码 | ✅ |
| `shell_exec` | 在沙箱中执行 Shell 命令 | ✅ |
| `memory_search` | 搜索 Agent 记忆 | ❌ |
| `memory_store` | 存储记忆条目 | ❌ |

### 9.2 L0 工具调用流程

1. L0 将工具 schema 注入 LLM system prompt
2. LLM 输出中如包含 `<tool_call>{"tool": "python_exec", "code": "..."}</tool_call>`
3. L0 解析 XML 标签，提取 JSON payload
4. 调用 `ToolRegistry.invoke(name, params)`
5. 将工具结果反馈给 LLM，合成最终答案
6. 最多进行 5 轮工具调用（防止无限循环）

### 9.3 注册自定义工具

```python
from more_core.tools.registry import ToolDefinition, ToolResult

async def my_handler(params):
    return ToolResult(
        tool="my_tool",
        success=True,
        output=params["input"].upper(),
    )

core.tools.register(ToolDefinition(
    name="my_tool",
    description="将输入转为大写",
    parameters_schema={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "要转换的文本"},
        },
        "required": ["input"],
    },
    handler=my_handler,
    requires_sandbox=False,
    tags=("text",),
))
```

### 9.4 工具统计

```python
stats = core.tools.stats()
# {"total": 5, "sandboxed": 2, "tools": ["python_exec", "shell_exec", ...]}
```

---

## 10. 记忆系统

### 10.1 三路记忆

| 类型 | 枚举值 | 用途 |
|------|--------|------|
| 情景记忆 | `MemoryKind.EPISODIC` | 交互历史、任务执行记录 |
| 语义记忆 | `MemoryKind.SEMANTIC` | 知识、概念、事实 |
| 程序记忆 | `MemoryKind.PROCEDURAL` | 技能、策略、流程 |

### 10.2 API

```python
from more_core.memory.store import MemoryEntry, MemoryKind

# 存储
core.memory.put(MemoryEntry(
    content="Python 的 list comprehension 语法...",
    kind=MemoryKind.SEMANTIC,
    tags=["python", "syntax"],
))

# 搜索（基于关键词匹配 + 评分排序）
results = core.memory.search("list comprehension", kind=MemoryKind.SEMANTIC, top_k=5)

# 列出
all_entries = core.memory.list(kind=MemoryKind.EPISODIC)

# 统计
stats = core.memory.stats()  # {"episodic": 10, "semantic": 5, "procedural": 2}
```

### 10.3 持久化

默认为内存模式（bounded deque，容量 2048 条/类型）。启用 SQLite 持久化：

```bash
export MORE_MEMORY_DB=data/memory.db
```

SQLite 版本使用 `check_same_thread=False` 确保线程安全，适合异步运行时。

---

## 11. 符号推理与治理

### 11.1 AOW 本体模型

基于 Agentic Ontology of Work v1.0 定义 8 类实体：

| 实体 | 说明 |
|------|------|
| `Agent` | 代理实体 |
| `Skill` | 技能/能力 |
| `Intent` | 用户意图 |
| `Context` | 上下文信息 |
| `Policy` | 治理策略 |
| `Memory` | 记忆 |
| `Confidence` | 置信度 |
| `Outcome` | 任务结果 |

### 11.2 默认本体约束

| 约束 ID | 优先级 | 描述 |
|---------|--------|------|
| `agent.sandboxed` | 10 (阻断) | Agent 生成的代码必须在沙箱执行 |
| `policy.metacog_review` | 9 (阻断) | 自修改必须人类审查 |
| `outcome.validated` | 8 (阻断) | 任务结果须与意图一致 |
| `confidence.threshold` | 7 | 低置信度输出须重试或升级 |

### 11.3 前向链规则引擎

L3 层运行一个轻量级前向链推理引擎（Rete-lite），支持：

- **声明式规则**：条件函数 + 动作函数
- **优先级排序**：CRITICAL(100) > HIGH(75) > NORMAL(50) > LOW(25)
- **6 种动作类型**：`assert`（添加事实）、`retract`（撤回事实）、`modify`、`annotate`（标注）、`violation`（违规）、`halt`（终止）
- **最大迭代**：50 轮（防止无限循环）

**默认治理规则**：

| 规则 | 优先级 | 条件 | 动作 |
|------|--------|------|------|
| `query_length_limit` | CRITICAL | query > 10000 字符 | violation |
| `ungated_self_improvement` | CRITICAL | 请求自改进但进化 gate 关闭 | violation |
| `dangerous_code_detection` | HIGH | 代码含 `os.system`/`eval`/`exec` 等 | violation + annotate |

### 11.4 自定义规则

```python
from more_core.ontology.rule_engine import Rule, Fact, RuleAction, RulePriority

def my_condition(facts):
    return any(f.kind == "request" and "SECRET" in f.data.get("query", "") for f in facts)

def my_action(facts, ctx):
    return [RuleAction(type="violation", payload={"message": "敏感词检测"})]

l3 = core.get_layer(LayerId.L3)
l3.rule_engine.add_rule(Rule(
    name="sensitive_word_filter",
    conditions=[my_condition],
    actions=[my_action],
    priority=RulePriority.HIGH,
    description="检测并阻断包含敏感词的查询",
))
```

### 11.5 严格模式

`strict_ontology=True`（默认）时，任何违规会抛出 `GovernanceError`，任务状态变为 `REJECTED`。

设为 `False` 时，违规仅记录到 `ctx.scratch["inference_annotations"]`，不阻断执行。

---

## 12. 进化引擎 (DGM)

> **默认关闭**。启用需要 `enable_evolution=True` + `allow_self_improvement=True`。

### 12.1 DGM 进化周期

```
snapshot → propose_variant → evaluate → verify/reject → archive
```

1. **快照**：获取当前最佳 Agent（或创建种子）
2. **变异提议**：基于父代 + 当前任务生成变异体
3. **评估**：通过 BenchmarkRunner 执行基准测试
4. **验证**：得分超过父代 + 阈值(0.02) → 标记为 `verified`
5. **归档**：结果写入 EvolutionArchive

### 12.2 BenchmarkRunner

```python
from more_core.evolution.benchmark import (
    Benchmark, BenchmarkCase, CaseResult,
)

class MyBenchmark(Benchmark):
    @property
    def name(self) -> str:
        return "custom"

    def cases(self) -> list[BenchmarkCase]:
        return [
            BenchmarkCase(id="t1", input="1+1", expected="2"),
            BenchmarkCase(id="t2", input="hello", expected="Hello"),
        ]

    async def evaluate(self, case: BenchmarkCase, agent_output: str) -> CaseResult:
        passed = case.expected in agent_output
        return CaseResult(
            case_id=case.id, passed=passed, actual=agent_output[:500],
            score=1.0 if passed else 0.0,
        )

core.benchmark_runner.register(MyBenchmark())
```

### 12.3 归档

EvolutionArchive 支持内存模式和 SQLite 持久化：

```bash
export MORE_EVOLUTION_DB=data/evolution.db
```

归档容量默认 100 个 Agent。当满时，驱逐性能最差的非最佳 Agent（最佳 Agent 永远不会被驱逐）。

---

## 13. 元认知与自修改

> **默认关闭**。启用需要 `enable_metacognition=True`。

### 13.1 Calibrator（置信度校准器）

基于滑动窗口（默认 128 条观测）计算：

- **confidence**：各层输出的平均置信度
- **accuracy**：基于外部信号推导（工具执行结果、治理通过率）
- **alignment**：`1 - |confidence - accuracy|`

```python
report = core.metacognition.get_calibration_report()
# {"confidence": 0.85, "accuracy": 0.80, "alignment": 0.95, "n": 42}
```

### 13.2 HyperAgent（受控自修改）

HyperAgent 可以提议修改系统自身的代码（仅限白名单目标文件）：

**安全约束**：

- 修改目标限于白名单：`l4_cognition.py`, `l3_symbolic.py`, `layer_router.py`, `config.py`
- 所有修改路径经过 `Path.resolve()` 防止路径遍历
- 修改前自动创建 VersionControl 快照
- 代码须通过 SandboxValidator 语法/安全检查
- 支持完整回滚

**状态流转**：

```
PENDING → APPROVED → APPLIED
                   → ROLLED_BACK
        → REJECTED
```

**治理工作流**：

```python
# 注册人类审批者
core.policy_workflow = GovernanceWorkflow(settings)
core.policy_workflow.register_approver("admin@example.com", "human")
core.metacognition.register_governance_workflow(core.policy_workflow)

# 审批提议
core.policy_workflow.approve("proposal_xxx", "admin@example.com")

# 应用已批准的提议
results = await core.metacognition.apply_approved_proposals(dry_run=False)
```

---

## 14. 沙箱执行

### 14.1 SubprocessSandbox（基线）

所有平台可用。特性：

- 超时控制（默认 20 秒，`TimeoutError` 自动 kill 进程）
- `stdin`/`stdout`/`stderr` 捕获
- 临时目录隔离（`run_python` 使用独立 tmpdir）
- Python 以 `-I` 隔离模式运行（禁用 site-packages 隐式导入）

### 14.2 LinuxSandbox（生产推荐）

Linux 环境自动启用，基于 cgroup v2 提供：

- CPU 配额限制
- 内存硬限制（OOM killer）
- PID 数量限制
- 继承 SubprocessSandbox 的超时 + 隔离

### 14.3 平台检测

```python
from more_core.sandbox.linux_sandbox import create_sandbox

sandbox = create_sandbox(timeout_s=20, memory_mb=512)
# Linux → LinuxSandbox；其他 → SubprocessSandbox
```

### 14.4 直接使用

```python
result = await core.sandbox.run_python("print('hello')")
print(result.stdout)      # "hello"
print(result.exit_code)   # 0
print(result.timed_out)   # False
print(result.duration_ms) # 150.3

result = await core.sandbox.run(["ls", "-la"], cwd="/tmp")
```

---

## 15. 插件开发

### 15.1 插件目录结构

```
plugins/
└── my-plugin/
    ├── plugin.json    # 清单（必须）
    ├── main.py        # 入口模块（必须导出 class Plugin）
    └── README.md      # 文档（可选）
```

### 15.2 plugin.json 清单

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "description": "我的行业插件",
  "author": "QNMing",
  "entry_point": "main",
  "capabilities": ["custom_tool", "custom_layer"],
  "dependencies": ["numpy>=1.20"],
  "min_core_version": "0.3.0"
}
```

- `dependencies`：支持两种格式
  - **pip 包**：含版本运算符（`numpy>=1.20`），系统会检查是否已安装
  - **插件依赖**：纯名称（`other-plugin`），系统会先激活依赖插件

### 15.3 脚手架生成

```python
from more_core.plugins.sdk import scaffold_plugin

scaffold_plugin("./plugins", "my-plugin", description="My Plugin", version="0.1.0")
```

生成的 `main.py`：

```python
from more_core.plugins.sdk import PluginBase, PluginContext

class Plugin(PluginBase):
    NAME = "my-plugin"
    VERSION = "0.1.0"
    DESCRIPTION = "My Plugin"

    async def activate(self, ctx: PluginContext) -> None:
        await super().activate(ctx)
        # 在这里注册工具、替换层、订阅事件

    async def deactivate(self) -> None:
        await super().deactivate()
```

### 15.4 插件 activate 时可做的事

```python
async def activate(self, ctx: PluginContext) -> None:
    await super().activate(ctx)

    # 1. 注册自定义工具
    ctx.core.tools.register(ToolDefinition(...))

    # 2. 替换层实现
    ctx.core.replace_layer(MyCustomL4())

    # 3. 注册自定义管道
    ctx.core.router.register_pipeline(TaskType.PLUGIN_DEFINED, [...])

    # 4. 订阅事件
    ctx.event_bus.subscribe("task.completed", self.on_task_done)

    # 5. 注册服务
    ctx.core.registry.register(ServiceMetadata(...))

    # 6. 添加规则引擎规则
    l3 = ctx.core.get_layer(LayerId.L3)
    l3.rule_engine.add_rule(Rule(...))
```

### 15.5 插件生命周期

```
discover() → load() → activate(ctx) → [运行] → deactivate()
```

- **自动发现**：`core.start()` 时扫描 `plugin_dir` 下所有 `plugin.json`
- **自动激活**：按依赖顺序递归激活
- **安全停用**：检查反向依赖，被其他活跃插件依赖的不可停用

---

## 16. 事件总线

### 16.1 概述

零耦合的异步发布-订阅机制，L0–L5 层及外部观察者通过事件通信。

### 16.2 内置事件主题

| 主题 | 触发时机 | data 内容 |
|------|---------|-----------|
| `task.started` | 任务开始执行 | `{id, type, pipeline}` |
| `task.completed` | 任务执行完成 | `{id, status, duration_ms}` |
| `layer.started` | 单层开始处理 | `{task_id, layer}` |
| `layer.completed` | 单层处理完成 | `{task_id, layer, step}` |
| `metacog.proposal.status` | HyperAgent 提议状态变更 | `{id, target, status}` |

### 16.3 订阅与取消

```python
async def on_task_done(event):
    print(f"Task {event.data['id']} finished: {event.data['status']}")

unsub = core.event_bus.subscribe("task.completed", on_task_done)

# 取消订阅
unsub()
```

### 16.4 通配符订阅

```python
core.event_bus.subscribe("*", my_global_handler)  # 接收所有事件
```

### 16.5 特性

- **异步非阻塞**：发布者不等待处理者完成
- **优雅关闭**：`stop()` 会等待所有进行中的 handler 完成
- **容错**：单个 handler 异常不影响其他 handler

---

## 17. 服务注册

轻量级进程内服务发现：

```python
from more_core.core.types import ServiceMetadata

core.registry.register(ServiceMetadata(
    name="my-service",
    version="1.0.0",
    provider="my-plugin",
    endpoint="http://localhost:9090",
    capabilities=["search", "index"],
))

# 查询
svc = core.registry.get("my-service")
all_svcs = core.registry.list_all()
by_provider = core.registry.list_by_provider("my-plugin")

# 健康检查
is_healthy = await core.registry.health_check("my-service")

# 注销
core.registry.unregister("my-service")
```

---

## 18. 审计日志

### 18.1 格式

JSONL（每行一条 JSON），路径由 `audit_log_path` 配置（默认 `logs/audit.jsonl`）。

```json
{"id": "audit_a1b2c3d4e5", "timestamp": 1714625000.0, "actor": "anonymous", "action": "execute_start", "entity": "task", "payload": {"task_id": "task_xxx", "task_type": "nlp_task", "pipeline": ["L4", "L3", "L1", "L0"]}}
```

### 18.2 自动记录的事件

| action | 触发时机 |
|--------|---------|
| `start` | MoRECore 启动 |
| `stop` | MoRECore 关闭 |
| `execute_start` | 任务开始 |
| `execute_end` | 任务完成 |

### 18.3 线程安全

AuditLogger 使用 `threading.Lock` 序列化写入，可安全地在多线程/多协程环境中使用。

### 18.4 手动写入

```python
core.audit.log(
    actor="admin",
    action="config_change",
    entity="settings",
    key="enable_evolution",
    old_value=False,
    new_value=True,
)
```

---

## 19. 安全机制

### 19.1 多层防护矩阵

| 威胁 | 防护机制 | 位置 |
|------|---------|------|
| 路径遍历 | `Path.resolve()` + project_root 校验 | HyperAgent |
| JSON 注入 | `json.dumps()` 安全序列化 | VersionControl |
| CORS 滥用 | 环境变量白名单（非 `*`） | API Server |
| 不安全代码执行 | L3 规则引擎预检 + 沙箱隔离 | L0 + L3 |
| 未授权自修改 | 功能门控 + 治理工作流 + 审计 | PolicyEnforcer + HyperAgent |
| LLM 注入 | 工具调用 JSON 严格解析 | L0 |
| 无限循环 | 工具调用轮数限制（5）、规则引擎迭代限制（50） | L0 + RuleEngine |
| 超时失控 | per-task `asyncio.wait_for` + 沙箱 timeout | Orchestrator + Sandbox |
| 并发写入 | `threading.Lock` 保护审计日志 | AuditLogger |

### 19.2 功能门控策略

| 功能 | 环境变量 | 默认 | 启用条件 |
|------|---------|------|---------|
| L2 进化 | `MORE_ENABLE_EVOLUTION` | 关闭 | 设为 `1` + request `allow_self_improvement=True` |
| L5 自修改 | `MORE_ENABLE_METACOGNITION` | 关闭 | 设为 `1` + request `allow_self_improvement=True` |
| L3 符号推理 | `MORE_ENABLE_SYMBOLIC` | 开启 | 设为 `0` 关闭 |

### 19.3 PolicyEnforcer 前置检查

在管道执行前自动检查：

- `allow_self_improvement=True` 但 `enable_metacognition=False` → 拒绝
- `timeout_s <= 0` 或 `> 600` → 拒绝

---

## 20. 故障排查

### 20.1 Ollama 连接失败

```
LLMError: Cannot connect to Ollama at http://localhost:11434 – is the server running?
```

**解决**：确认 `ollama serve` 已启动，端口可达。

### 20.2 Ollama 首次加载超时

```
LLMError: Ollama read timeout (model may still be loading). Retry or increase timeout.
```

**解决**：首次使用新模型时，Ollama 需要加载模型到内存（可能需要 60-120 秒）。增大 `timeout_s`：

```bash
export MORE_OLLAMA_TIMEOUT=180  # 或在 LLMProviderConfig 中设置
```

### 20.3 所有 Provider 失败

```
LLMError: all providers failed: ...
```

**解决**：检查 fallback 链中至少一个 Provider 可用：

```python
health = await core.llm.health()
print(health)
```

### 20.4 治理拒绝

```json
{"status": "rejected", "output": "rejected: symbolic violations: [...]"}
```

**解决**：检查 `reasoning_chain` 中 L3 层的违规详情。常见原因：

- 查询过长（> 10000 字符）
- 请求自改进但 evolution gate 关闭
- 生成代码包含危险模式

### 20.5 任务超时

```json
{"status": "failed", "output": "task timed out after 60.0s"}
```

**解决**：增大 `timeout_s` 或优化查询复杂度：

```python
req = TaskRequest(query="...", timeout_s=120.0)
```

### 20.6 测试验证

```bash
cd more_core
python3 -m pytest tests/ -v
# 应显示 95 passed
```

### 20.7 VPN/代理网络问题

系统运行时如遇网络超时（如 LM Studio/Ollama 连接失败），需检查：
- HTTP 代理端口（Lantern 默认 50768）是否被占用
- SOCKS 端口 50051 是否被其他服务占用
- 必要时通过 `export http_proxy="" && export https_proxy=""` 禁用代理

---

## 21. Hands 系统

Hands 是 MoRE OS v0.5.0 引入的自主执行 Agent 包，可定时或按需运行。

### 21.1 注册的内置 Hands

| Hand ID | 名称 | 类别 | 定时策略 |
|---------|------|------|----------|
| `researcher` | 研究员 | research | 6:00 AM |
| `coder` | 编码员 | coding | — |
| `digest` | 文摘员 | digest | 8:00 AM |
| `monitor` | 监控员 | monitoring | `*/5 * * * *` (每5分钟) |
| `browser` | 浏览器 | browser | — |

### 21.2 Hands API

```bash
# 列出所有 Hands
curl http://127.0.0.1:8001/api/v1/hands

# 列出注册清单
curl http://127.0.0.1:8001/api/v1/hands/registry

# 激活 Hand
curl -X POST http://127.0.0.1:8001/api/v1/hands/researcher/activate

# 手动触发执行
curl -X POST http://127.0.0.1:8001/api/v1/hands/researcher/run

# 查看状态
curl http://127.0.0.1:8001/api/v1/hands/researcher/status

# 保存/恢复状态
curl -X POST http://127.0.0.1:8001/api/v1/hands/researcher/save
curl -X POST http://127.0.0.1:8001/api/v1/hands/researcher/wakeup

# 克隆 Hand
curl -X POST http://127.0.0.1:8001/api/v1/hands/researcher/clone \
  -H "Authorization: Bearer $MORE_API_KEY" \
  -d '{"new_id": "researcher_v2", "config": {}}'
```

---

## 22. ZEN 零信任规则

MoRE OS v0.5.0 内置 15 条 ZEN 零信任规则，分为 6 个类别：

### 22.1 规则列表

| 规则ID | 名称 | 类别 | 严重级别 |
|--------|------|------|----------|
| ZEN-01 | 零信任原则 | SAFETY | P1_CRITICAL |
| ZEN-02 | 最小权限 | SAFETY | P1_CRITICAL |
| ZEN-03 | 纵深防御 | SAFETY | P1_CRITICAL |
| ZEN-04 | 代码简洁 | SIMPLICITY | P3_MINOR |
| ZEN-05 | 接口简洁 | SIMPLICITY | P3_MINOR |
| ZEN-07 | 决策可控 | CONTROL | P2_MAJOR |
| ZEN-08 | 状态可控 | CONTROL | P2_MAJOR |
| ZEN-09 | 演进可控 | CONTROL | P2_MAJOR |
| ZEN-10 | 操作追溯 | TRACEABLE | P2_MAJOR |
| ZEN-11 | 决策追溯 | TRACEABLE | P2_MAJOR |
| ZEN-12 | 异常追溯 | TRACEABLE | P2_MAJOR |
| ZEN-16 | LLM调用 | LLM_SPECIFIC | P2_MAJOR |
| ZEN-17 | LLM输出 | LLM_SPECIFIC | P1_CRITICAL |
| ZEN-18 | 成本控制 | LLM_SPECIFIC | P2_MAJOR |
| ZEN-19 | 绝对禁止 | PROHIBITION | P0_FATAL |

### 22.2 严重级别

| 级别 | 值 | 说明 |
|------|-----|------|
| P0_FATAL | `p0_fatal` | 绝对禁止，违反即致命 |
| P1_CRITICAL | `p1_critical` | 严重问题 |
| P2_MAJOR | `p2_major` | 重要问题 |
| P3_MINOR | `p3_minor` | 一般问题 |

### 22.3 ZEN API

```bash
# 获取所有规则
curl http://127.0.0.1:8001/api/v1/zen/rules

# 合规报告
curl http://127.0.0.1:8001/api/v1/zen/compliance

# 按严重级别筛选违规
curl "http://127.0.0.1:8001/api/v1/zen/violations?severity=p1_critical"

# 解决违规
curl -X POST http://127.0.0.1:8001/api/v1/zen/violations/0/resolve \
  -H "Authorization: Bearer $MORE_API_KEY" \
  -d '{"resolution": "已修复"}'
```

---

## 23. 安全层总览

MoRE OS v0.5.0 提供 16 层安全防护：

| 层ID | 安全层 | 状态 |
|------|--------|------|
| 1 | API Authentication | `active` (dev_mode 无 API Key) |
| 2 | RBAC | `active` / `disabled` |
| 3 | Input Validation | `active` |
| 4 | Path Traversal Protection | `active` |
| 5 | Command Injection Prevention | `active` |
| 6 | Sandbox Isolation | `active` |
| 7 | Rate Limiting | `active` |
| 8 | Circuit Breaker | `active` |
| 9 | Secret Redaction | `active` |
| 10 | Audit Logging | `active` |
| 11 | Policy Enforcement | `active` |
| 12 | ZEN Rules | `active` |
| 13 | Incident Response | `active` |
| 14 | Taint Tracking | `active` |
| 15 | Request Signing | `available` |
| 16 | Output Filtering | `active` |

```bash
# 安全总览
curl http://127.0.0.1:8001/api/v1/security/status

# RBAC 角色列表
curl http://127.0.0.1:8001/api/v1/security/rbac/roles

# 分配角色
curl -X POST http://127.0.0.1:8001/api/v1/security/rbac/assign \
  -H "Authorization: Bearer $MORE_API_KEY" \
  -d '{"user_id": "user1", "role": "admin"}'

# 污染追踪
curl http://127.0.0.1:8001/api/v1/security/taint
curl http://127.0.0.1:8001/api/v1/security/taint/violations

# 输出过滤
curl http://127.0.0.1:8001/api/v1/security/output-filter/stats
curl -X POST http://127.0.0.1:8001/api/v1/security/output-filter/scan \
  -H "Authorization: Bearer $MORE_API_KEY" \
  -d '{"text": "some text to scan"}'
```

---

## 24. CJK/国际化支持

MoRE OS 内核全面支持中文、日文、韩文（CJK）文本处理：

### 24.1 语言自动检测

系统自动检测查询语言，根据结果调整行为：

| 检测结果 | L0 System Prompt | L4 分解提示词 |
|----------|-----------------|---------------|
| `zh` | 中文回答指令 | 中文分解提示 |
| `ja` | 日本語回答指示 | 英文（fallback） |
| `ko` | 한국어 답변 지시 | 英文（fallback） |
| `en` | English | English |

检测算法基于字符码点范围统计，阈值为 0.2（即文本中 20%+ 的字符属于 CJK 时触发）。

### 24.2 语义长度估算

中文字符信息密度高于英文（每字 ≈ 2 个英文单词），系统使用 `semantic_length()` 进行语义级键度估算：

```python
from more_core import semantic_length

# 英文: 原始长度
assert semantic_length("hello world") == 11

# 中文: 每字 ×2
assert semantic_length("你好世界") == 8

# 混合
assert semantic_length("hello你好") == 9  # 5 + 2×2
```

影响范围：
- **L4 难度估算**：200 个中文字 = 400 语义单位，难度 +1
- **查询长度限制**：本体引擎 16000、规则引擎 10000（语义单位）
- **效果**：5001 个中文字 = 10002 语义单位 → 触发长度违规

### 24.3 记忆搜索标准化

记忆子系统使用 **Unicode NFKC 标准化 + casefold**：

- 全角 `ＡＢＣ` → 半角 `abc`
- 兼容字符分解（Ⅴ → V）
- 大小写无关匹配

这确保搜索“Python”能匹配内容中的“Ｐｙｔｈｏｎ”。

### 24.4 插件中使用 CJK 工具

```python
from more_core import (
    detect_language,
    semantic_length,
    is_cjk_char,
    is_predominantly_cjk,
    normalize_for_search,
)
from more_core.core.unicode_utils import (
    display_width,
    truncate_display,
    cjk_ratio,
)

# 检测语言
detect_language("请帮我写一段代码")  # "zh"

# 安全截断（CJK 宽字符感知）
truncate_display("你好世界测试", max_width=8)  # "你好世…"
```

### 24.5 JSON 输出

所有 JSON 输出（审计日志、CLI、REST API）均使用 `ensure_ascii=False`，中文字符直接输出而非转义为 `\uXXXX`。

### 24.6 文件 I/O

所有文件读写均明确指定 `encoding="utf-8"`，包括：
- 沙箱 stdout/stderr 解码
- 插件清单、脏本快照
- 审计日志
- SQLite 存储

---

## 25. 附录：环境变量速查表

*（原第 21 章内容不变）*

---

### 25.2 LLM Provider 环境变量

| 变量 | Provider | 默认值 | 说明 |
|------|----------|--------|------|
| `MORE_OLLAMA_ENDPOINT` | ollama | `http://localhost:11434` | Ollama API 端点 |
| `MORE_OLLAMA_MODEL` | ollama | `qwen2.5:7b` | 模型名 |
| `MORE_LMSTUDIO_ENDPOINT` | lmstudio | `http://localhost:1234/v1` | LM Studio 端点 |
| `MORE_LMSTUDIO_MODEL` | lmstudio | `gemma-4-coder` | 模型名 |
| `MORE_LLM_FALLBACK_CHAIN` | 全局 | (注册顺序) | fallback 优先级 (逗号分隔) |
| `MORE_OPENAI_API_KEY` | openai | — | OpenAI API Key |

### 25.3 dotenv 配置 (v0.5.1)

MoRE OS 自动加载 `more_core/.env` 文件：

```bash
# more_core/.env
MORE_OLLAMA_ENDPOINT=http://localhost:11434
MORE_OLLAMA_MODEL=qwen2.5:7b
MORE_LMSTUDIO_ENDPOINT=http://localhost:1234/v1
MORE_LMSTUDIO_MODEL=qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled
MORE_LLM_FALLBACK_CHAIN=ollama,lmstudio
```

---

> **版本**：QNMing MoRE OS v0.5.1 · **许可**：Apache-2.0 · **更新**：2026-05-23
