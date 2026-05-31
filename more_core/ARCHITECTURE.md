# QNMing MoRE OS v0.5.0 — 架构白皮书

本文档为 **QNMing MoRE OS Agent 内核** v0.5.0 的工程化架构说明，基于实际代码测试验证。

## 1. 六层装配关系

```text
           ┌────────────────────────────────────────────────────┐
           │             runtime.MoRECore (Orchestrator)        │
           └──────────────────────────┬─────────────────────────┘
                                      │ execute(TaskRequest)
                                      ▼
                  ┌───────────────────────────────────┐
                  │      router.LayerRouter           │  难度感知 / OMAC
                  └──────┬──────────────┬─────────────┘
                         │              │
     ┌───────────────────┼──────────────┼───────────────────┐
     ▼                   ▼              ▼                   ▼
 L5 Metacognition   L4 Cognition    L3 Symbolic         L2 Evolution
 calibrator /       task parser /   ontology /          archive /
 hyperagent*        planner         rule engine         dgm*
     │                   │              │                   │
     └───────┬───────────┴──────────────┴────────┬──────────┘
             ▼                                   ▼
        L1 Orchestration (agent handoff / routing) 
                         │
                         ▼
                    L0 Execution
            (tool / sandbox / llm / api)

  * L2 DGM、L5 HyperAgent 默认关闭；开启需 governance 审计 + sandbox 隔离。
```

## 2. 支撑子系统

| 子系统 | 模块 | 关键类 | 作用 |
|--------|------|--------|------|
| 服务注册 | `core.service_registry` | `ServiceRegistry` | 服务发现与版本索引 |
| 事件总线 | `core.event_bus` | `EventBus` | 异步发布订阅，零耦合 |
| 配置管理 | `core.config` | `Settings` | 环境变量/文件驱动 |
| 插件系统 | `plugins.manager` / `plugins.sdk` | `PluginManager`, `PluginBase`, `scaffold_plugin` | 动态加载 + 依赖解析 + SDK |
| LLM 管理 | `llm.manager` | `LLMManager` | 多 Provider + fallback |
| **工具注册** | `tools.registry` / `tools.builtins` | `ToolRegistry`, `ToolDefinition` | L0 结构化工具调用 |
| **层路由** | `router.layer_router` | `LayerRouter`, `RoutingDecision`, `DEFAULT_PIPELINES` | 难度感知路由 + 可配置管道 + 插件扩展 |
| 沙箱 | `sandbox.subprocess_sandbox` / `sandbox.linux_sandbox` | `SubprocessSandbox`, `LinuxSandbox`, `create_sandbox` | 超时/内存限制 + Linux cgroup v2 硬化 |
| 记忆 | `memory.store` / `memory.sqlite_store` | `MemoryStore`, `SQLiteMemoryStore` | 三路记忆 + SQLite 持久化 |
| **规则引擎** | `ontology.rule_engine` | `RuleEngine`, `Rule`, `Fact` | 前向链推理 + 治理规则 |
| 本体 | `ontology.engine` | `OntologyEngine` | AOW 约束检查 |
| 进化 | `evolution.dgm` / `evolution.benchmark` / `evolution.sqlite_archive` | `DGMEngine`, `BenchmarkRunner`, `SQLiteEvolutionArchive` | 受控变异 + 评估回路 + SQLite 持久化 |
| 元认知 | `metacognition.calibrator` | `Calibrator`, `HyperAgent` | 置信度校准 + 自修改 |
| 治理 | `governance.audit` | `AuditLogger`, `PolicyEnforcer` | 合规与审计 |
| **Hands 系统** | `hands.registry` / `hands.manager` / `hands.builtins` | `HandRegistry`, `HandManager`, 5 内置 Hands | 自主执行 Agent 包 + 定时调度 |
| **ZEN 规则** | `zen_rules` | `ZENRulesEnforcer`, `ZENRule`, `ViolationRecord` | 零信任规则执行与合规检查 |
| **安全层** | `security.rbac` / `security.taint` / `security.output_filter` | `RBACManager`, `TaintTracker`, `OutputFilter` | RBAC + 污染追踪 + 输出过滤 |
| **指标采集** | `metrics` | `MetricsCollector` | 请求量/延迟/错误率采集 |
| **事件响应** | `incident_response` | `IncidentManager`, `Incident` | 主动异常检测与响应 |
| **LLM 状态管理** | `llm.state_manager` | `LLMStateManager` | LLM 参数动态调整 + 使用统计 |
| **推理路由** | `llm.reasoning` | `ReasoningRouter` | Reasoning 模型 budget_tokens 路由 |
| **模型别名** | `llm.model_aliases` | `ModelAliasRegistry` | 模型别名解析 |
| **通道重连** | `channels.reconnect` | `ReconnectManager` | 消息通道断线重连 |
| **热重载** | `runtime.hot_reload` | `HotReloader` | 运行时子系统热重载 |
| **命令注册** | `commands.registry` | `CommandRegistry` | 统一斜杠命令注册表 |
| **技能管理** | `skills.base` | `SkillManager` | 模块化技能执行 |
| **工作流引擎** | `workflows.engine` | `WorkflowEngine` | 多步骤编排 |
| **部署管理** | `deploy.manager` | `DeploymentManager` | 部署类型管理 |
| **会话管理** | `runtime.sessions` | `SessionManager` | 用户会话管理 |
| **请求缓存** | `optimization` | `RequestCache`, `RateLimiter`, `CircuitBreaker` | 请求缓存 + 限流 + 熔断 |
| **流式输出** | `runtime.orchestrator.stream_execute` | SSE generator | token 级实时流式推送 |
| **MCP Server** | `mcp.server` | `MCPServer`, `MCPRequestHandler` | 暴露 29 个工具给外部 Agent (Codex/Claude) |
| **MCP Client** | `mcp.client` / `mcp.transport` | `MCPClient`, `ProcessTransport` | 连接外部 MCP Server (filesystem 等) |
| **A2A 协议** | `a2a.client` | `A2AServer`, `A2AClient` | Agent-to-Agent 任务委托 (Google A2A) |

## 3. 扩展点（对外稳定 API）

- `more_core.layers.base.Layer` — 实现自定义层或替换基线层
- `more_core.plugins.PluginInterface` — 发布行业 Pack
- `more_core.plugins.sdk.PluginBase` — 便捷基类 + `scaffold_plugin()` 脚手架
- `more_core.tools.ToolRegistry` — 注册自定义工具供 L0 调用
- `more_core.router.LayerRouter.register_pipeline()` — 插件运行时注册/覆盖管道模板
- `more_core.ontology.RuleEngine` — 自定义规则 + 条件/动作对
- `more_core.evolution.Benchmark` — 自定义评估基准套件
- `more_core.llm.LLMProvider` — 接入新模型服务
- `more_core.ontology.OntologyEntity` — 领域本体扩展
- `more_core.hands.registry` — 注册自定义 Hand
- `more_core.zen_rules` — 扩展 ZEN 规则
- `more_core.security.rbac` — 扩展 RBAC 角色权限
- `more_core.llm.state_manager` — LLM 状态监控扩展
- `more_core.mcp.server.MCPServer` — 注册 MCP 工具/资源，暴露给外部 Agent
- `more_core.mcp.client.MCPClient` — 连接外部 MCP Server
- `more_core.a2a.client.A2AServer` — 接收 A2A 任务委托

## 4. 已验证的业务流程

### 4.1 任务执行管道（L4→L3→L1→L0）

```
TaskRequest → PolicyEnforcer.check() → LayerRouter.route()
→ L4 CognitionLayer (任务解析/难度评估)
→ L3 SymbolicLayer (本体约束/规则引擎)
→ L1 OrchestrationLayer (Agent 路由/协作决策)
→ L0 ExecutionLayer (LLM 生成 + 工具调用 + 沙箱执行)
→ TaskResult
```

### 4.2 LLM Provider 验证

| Provider | 状态 | 端点 | 验证模型 |
|----------|------|------|----------|
| `lmstudio` | ✅ 正常 | `localhost:1234/v1` | `qwen3.6-27b` |
| `ollama` | ✅ 正常 | `localhost:11434` | 2 个模型 |

### 4.3 Hands 系统

已注册 6 个内置 Hands：`researcher`(6:00AM)、`coder`、`digest`(8:00AM)、`monitor`(*/5min)、`browser`、`mahjong`(plugin)。

### 4.4 流式输出 (SSE)

```
POST /api/v1/tasks/stream  →  SSE Stream
  → event: pipeline (L4→L3→L1→L0)
  → event: layer_done (L4/L3/L1)
  → data: {"token": "..."}  (L0 token stream)
  → event: done
```

### 4.5 MCP 双向协议

**Server 模式** — MoRE OS 作为 MCP Server，暴露 29 个工具：

```bash
# CLI 入口
.venv/bin/python3 -m more_core.cli mcp-serve

# Codex 集成 (.codex.json)
{"mcpServers": {"more-os": {"command": ".venv/bin/python3", "args": ["-m", "more_core.cli", "mcp-serve"]}}}
```

**Client 模式** — MoRE OS 连接外部 MCP Server：

```
GET  /api/v1/mcp/servers     # 列出已连接
POST /api/v1/mcp/connect/filesystem  # 连接 npx MCP filesystem server
POST /api/v1/mcp/tools/{s}/{t}       # 调用工具
```

### 4.6 A2A Agent-to-Agent

```
POST /a2a  (JSON-RPC)
  → agent/card    — 获取 Agent 能力卡片
  → tasks/send    — 发送任务
  → tasks/get     — 查询任务状态
  → tasks/cancel  — 取消任务
```

### 4.7 安全层

16 层安全防护已激活：API Auth / RBAC / Input Validation / Path Traversal / Command Injection / Sandbox / Rate Limiting / Circuit Breaker / Secret Redaction / Audit / Policy / ZEN Rules / Incident Response / Taint Tracking / Request Signing / Output Filtering。

## 5. 持久化与环境变量

| 环境变量 | 作用 |
|----------|------|
| `MORE_MEMORY_DB` | SQLite 路径，启用 `SQLiteMemoryStore` 持久记忆 |
| `MORE_EVOLUTION_DB` | SQLite 路径，启用 `SQLiteEvolutionArchive` 持久进化归档 |
| `MORE_CORS_ORIGINS` | API CORS 允许源（逗号分隔），默认 localhost |

缺省为内存模式；生产部署设置以上变量即可无代码切换。完整环境变量列表见 `USER_MANUAL.md` §25。
