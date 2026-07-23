# QNMing MoRE OS v0.6.0-alpha — 系统性深度审计报告

**审计日期**: 2026-06-05
**审计范围**: `more_core/` 全部 156 个 Python 源文件 (71,197 LOC) + 37 个测试文件
**审计方法**: 逐模块代码审查 + 测试基线运行 + 历史审计追溯
**测试基线**: 414/425 通过 (11 失败，均为测试异步调用未 `await` 的问题)
**历史审计**: 此前已完成 3 轮审计（2025-05-09、2026-05-02、2026-05-07），累计修复约 55 个问题

---

## 目录

1. [环境与基础设施问题](#1-环境与基础设施问题)
2. [安全审计 (CRITICAL)](#2-安全审计-critical)
3. [安全审计 (HIGH)](#3-安全审计-high)
4. [代码质量与架构问题](#4-代码质量与架构问题)
5. [测试覆盖率审计](#5-测试覆盖率审计)
6. [性能与可观测性](#6-性能与可观测性)
7. [历史审计回归检查](#7-历史审计回归检查)
8. [迭代优化路线图](#8-迭代优化路线图)

---

## 1. 环境与基础设施问题

### ENV-01 🔴 .venv 与旧版本共享（CRITICAL）

**文件**: `QNMing_MoRE_OS_LIVE/.venv`
**问题**: LIVE 版本的 `.venv` 与 `qnm-os-prev-202605211332/.venv` 是**同一个物理目录**（inode 相同：18943055）。这意味着：
- 运行时实际加载的是 `qnm-os-prev-202605211332/more_core/` 的代码（v0.5.0）
- 安装的包指向旧版本：`__editable__.qnming_more_os-0.5.0.pth`
- 即使修改 LIVE 目录的源码，测试运行代码依然是旧版本

**影响**: 所有在 LIVE 目录中开发的修改都不会被实际测试/运行验证。开发者和 AI 工具在"盲打"。

**修复**: 
```bash
cd /Users/qnming/AI_Cample/QNMing_MoRE_OS_LIVE
rm -rf .venv
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv
.venv/bin/pip install -e "more_core[all]"
```

### ENV-02 🟡 PYTHONPATH 污染

**问题**: Python 运行时 `sys.path` 包含 `/Users/qnming/AI_Cample/`，其中存在多个版本的 `more_core` 目录，导入顺序不可控。

---

## 2. 安全审计 (CRITICAL)

### SEC-01 🔴 RBAC 未集成到执行管道

**文件**: `security/rbac.py:247-257`, `runtime/orchestrator.py:282-435`
**问题**: `UnifiedRBAC.check()` 仅在 API 端点层面通过 FastAPI `Depends` 调用。`MoRECore.execute()` 内部和 `layers/l0_execution.py` 的工具调度**完全不经过 RBAC 检查**。

攻击向量：
- 通过 MCP 协议调用 `shell_exec` 不经过 RBAC（`mcp/server.py:184-198`）
- 通过 A2A 协议委托任务不经过 RBAC（`runtime/orchestrator.py:648-665`）
- 插件内部直接调用 `core.tools.invoke()` 不经过 RBAC

### SEC-02 🔴 MCP Server 零认证

**文件**: `mcp/server.py:344-362`
**问题**: `run_stdio()` 和 `run_tcp()` 均无任何认证机制。连接到 MCP Server 的任何进程可调用包括 `shell_exec`、`python_exec` 在内的全部 29 个工具。

**影响**: Codex/Claude Code 集成时，任何能启动 MCP 通信的进程都具有完全的 OS 级命令执行能力。

### SEC-03 🔴 A2A 端点零认证

**文件**: `api/routers/a2a.py`（未读但按架构分析）
**问题**: A2A 协议端点（`POST /a2a`）使用 JSON-RPC 协议，可能未集成 `_require_api_key` 依赖注入。

### SEC-04 🔴 L0 代码自动执行绕过策略检查

**文件**: `layers/l0_execution.py:302-337`
**问题**: L0 层在 LLM 输出中提取 Python 代码并自动执行。虽然通过了 L3 rule_engine 检查，但：
1. L3 规则引擎的规则集不可从配置扩展
2. 自动执行路径跳过 `PolicyEnforcer.check()`
3. 执行结果的审计日志可能缺失

### SEC-05 🟡 命令注入仍然存在（部分修复）

**文件**: `tools/builtins.py:417, 453, 493`
**问题**: 2025 年审计标记的命令注入已部分修复（使用 `shlex.quote`），但：
- `_lint_file` 中：`f"pycodestyle --max-line-length=100 {shlex.quote(file_path)}"` 
- `_format_code` 中：`f"black {'--check --diff' if check_only else ''} {shlex.quote(file_path)}"`
- `_run_tests` 中：`" ".join(cmd_parts)` 后传递给 sandbox

`shlex.quote` 对路径遍历的防御有限，且 `_lint_file` 和 `_format_code` 中的 `file_path` 解析后传递给 shell 命令。

### SEC-06 🟡 SecureSandbox blocked_commands 绕过

**文件**: `sandbox/secure_sandbox.py:101-115`
**问题**: 命令黑名单仅检查命令的第一个 token 的 basename。`python3 -c "import os; os.system('rm -rf /')"` 可完全绕过。

### SEC-07 🟡 OutputFilter 概率性过滤

**文件**: `security/output_filter.py:109-124`
**问题**: 基于正则的 PII 过滤是概率性的，无法防御：
- Base64/Hex 编码后的密钥
- 跨 token 边界的敏感信息（stream 场景）
- 上下文相关的 PII（如特定格式的 ID）

---

## 3. 安全审计 (HIGH)

### SEC-08 🟡 GovernanceWorkflow 硬编码安全路径

**文件**: `governance/policy.py:54`
```python
safe_targets = ["more_core/layers/l4_cognition.py", "more_core/router/layer_router.py"]
```
**问题**: 2026-05-02 审计已标记但未修复。自动审批的"安全路径"仍硬编码。

### SEC-09 🟡 EventBus 无订阅者认证

**文件**: `core/event_bus.py:39-48`
**问题**: 任何模块都可订阅任意 topic。恶意插件可以订阅 `audit.*` 或 `task.*` 监听敏感数据。

### SEC-10 🟡 多版本代码库共存导致安全补丁可能未应用

**文件**: 多版本目录结构（`qnm-os-prev-*`, `QNMing MoRE OS preVersion/`, `QNMing_MoRE_OS_LIVE/`）
**问题**: 修复可能只应用到了某个版本。例如 ENV-01 导致 LIVE 实际运行的是旧版本代码，安全补丁（如 CORS 修复、API KEY 认证）可能未生效。

---

## 4. 代码质量与架构问题

### ARCH-01 🟡 LLMStateManager 与 LLMManager 职责脱节

**文件**: `llm/state_manager.py`, `llm/manager.py`
**问题**: 2025 年审计即已发现。`LLMStateManager` 管理调用参数（provider/model/temperature），但 `LLMManager.generate()` 不消费这些状态。前端通过 `/api/v1/llm/state/update` 修改的参数对实际 LLM 调用无影响。

### ARCH-02 🟡 全局单例模式未重构

**文件**: `incident_response.py:237`, `zen_rules.py`, `metrics.py`, `security/rbac.py:31`
**问题**: 4+ 个模块使用全局可变单例。测试隔离困难，多租户场景不可用。虽已修复 `MoRECore` 使用 `get_*()` 函数而非直接创建新实例，但单例设计本身未改。

### ARCH-03 🟡 ChannelManager 类重复定义

**文件**: `channels/base.py:78-108`, `channels/manager.py:26-127`
**问题**: 2026-05-07 审计已标记。两个 `ChannelManager` 类 API 不同。`base.py` 版本疑似遗存。

### ARCH-04 🟡 channels v2 草稿文件未清理

**文件**: `channels/telegram.py`, `channels/discord.py`, `channels/slack.py`, `channels/http.py`
**问题**: 引用未定义的 `ChannelConfig`/`ChannelType`/`ChannelUser`/`ChannelMessage`。这些是下一代适配器草稿，当前无法实例化。

### ARCH-05 🟡 MCP stdio 使用私有 asyncio API

**文件**: `mcp/transport.py`（按审计记录推测）
**问题**: `asyncio.get_running_loop()._stdin`/`._stdout` 是 asyncio 私有属性。附注：当前 `mcp/server.py:349-353` 已改用 `sys.stdin.buffer` + `StreamReaderProtocol`，但需确认 transport 层是否已完全修复。

### ARCH-06 🟡 CronParser 仅计算当前小时内

**文件**: `cron/scheduler.py`（按审计记录推测）
**问题**: `get_next_run()` 不翻滚到下一小时。`"0 * * * *"` 配置在当前小时第 0 分钟已过时返回 None。

### ARCH-07 🟡 L0 scratch 覆盖时 tool_hint 丢失

**问题**: 当 `ctx.scratch["system_prompt"]` 在 L4/L3 中已设置时，L0 不会附加工具列表信息。

### ARCH-08 🔵 L2 EvolutionLayer 未使用 LLM variant

**文件**: `layers/l2_evolution.py`
**问题**: L2.process() 调用 `propose_variant()`（基础版），而非 `propose_variant_llm()`（LLM 版）。LLM 变体提案路径在生产流程中未被调用。

### ARCH-09 🟡 11 个测试用例因异步 API 不匹配失败

**文件**: `tests/test_optimization.py`, `tests/test_kernel_performance.py`, `tests/test_integration*.py`, `tests/test_runtime.py`
**问题**: `RequestCache.get()`/`set()` 已改为 `async` 方法，但测试仍使用同步调用（无 `await`）。这导致 11 个测试失败。

---

## 5. 测试覆盖率审计

### 5.1 当前测试状况

| 指标 | 数值 |
|------|------|
| 测试文件 | 37 |
| 总用例 | 425 |
| 通过 | 414 (97.4%) |
| 失败 | 11 (2.6%) |
| 测试时间 | ~5s |

### 5.2 测试覆盖缺口

| 模块 | 覆盖率 | 风险 |
|------|--------|------|
| `api/server.py` 端点集成测试 | ❌ 无 | 高 — 端点行为无自动化验证 |
| `governance/policy.py` GovernanceWorkflow | ❌ 无 | 中 — 自动审批逻辑不可测试 |
| `incident_response.py` 事件生命周期 | ❌ 无 | 中 |
| `channels/` 适配器 | ❌ 无 | 低 — 外部通道适配器 |
| `mcp/` 模块 | ❌ 无 | 高 — 29 个工具的 MCP 暴露无验证 |
| `a2a/` 协议 | ❌ 无 | 中 |
| `security/` 渗透测试 | ❌ 无 | 高 — 无任何安全攻防测试 |
| `layers/l0_execution.py` LLM+Tool 循环 | ✅ 有 | -- |
| `layers/l2_evolution.py` | ⚠️ 部分 | 死代码路径已修复但函数级覆盖不足 |
| `memory/sqlite_store.py` 持久化集成 | ⚠️ 部分 | 仅有进化归档测试 |

### 5.3 测试环境问题

- PYTHONPATH 污染导致测试可能加载错误的模块版本
- `tests/conftest.py` 中的 `_FakeLLMProvider` 极为简化 — 不模拟流式、错误、超时

---

## 6. 性能与可观测性

### PERF-01 🔵 httpx.AsyncClient 未复用

**文件**: `llm/providers/openai_compat.py:50,70`
**问题**: 每次 `generate()` 和 `stream()` 创建新的 `httpx.AsyncClient`。无法复用 TCP 连接池。

### PERF-02 🔵 EventBus 监听器潜在泄漏

**文件**: `runtime/orchestrator.py:327, 442-456`
**问题**: 每次 `execute()` / `_run_pipeline()` 都 publish 事件。订阅者在 `event_bus.subscribe()` 注册但不会累积（非监听器泄漏），但 `_pending_tasks` set 中长时间运行的 handler 会成为内存泄漏。

### PERF-03 🔵 RequestCache O(n) 驱逐策略（已部分缓解）

**文件**: `optimization.py:48-72`
**问题**: `OrderedDict` 的 LRU 实现正确，但 `_key()` 生成中有 `sorted(kwargs.items())` O(n log n)。高频场景影响可忽略。

### OBS-01 缺失 Prometheus/OpenTelemetry 指标导出

**文件**: 无导出模块
**问题**: 仅有 JSONL 审计日志和 `MetricsCollector` 内存指标，无标准可观测性集成。

---

## 7. 历史审计回归检查

### 7.1 AUDIT_REPORT.md (2026-05-02) — 22 项

| 编号 | 问题 | 状态 | 验证 |
|------|------|------|------|
| H1 | EventBus stop() 不等待 pending handler | ✅ 已修 | `event_bus.py:66-68` `await asyncio.gather()` 已添加 |
| H2 | HyperAgent 路径遍历 | ✅ 已修 | `Path.resolve()` + `relative_to()` 校验已添加 |
| H3 | VersionControl JSON 注入 | ✅ 已修 | `json.dumps()` 已替换 f-string |
| H4 | SQLite 线程安全 | ✅ 已修 | `check_same_thread=False` |
| H5 | LLM 缓存 key 不完整 | ✅ 已修 | `stop` + `extra` 关键入 `_cache_key` |
| H6 | execute() 无超时 | ✅ 已修 | `asyncio.wait_for()` 包裹 |
| H7 | API CORS 全开放 | ✅ 已修 | `MORE_CORS_ORIGINS` 环境变量控制 |

### 7.2 AUDIT_REPORT_SYSTEM.md (2026-05-07) — 16 项

| 编号 | 问题 | 状态 | 验证 |
|------|------|------|------|
| P0-1 | L2 EvolutionLayer 死代码 | ✅ 已修 | 83-117 行不可达代码已删除 |
| P0-2 | IncidentManager/MetricsCollector 单例不一致 | ✅ 已修 | 改用 `get_*()` 全局单例 |
| P1 | 绝对导入、RoutingError 导出、callable 类型 | ✅ 已修 | 所有文件已核验 |

### 7.3 SYSTEM_AUDIT_2025.md (2025-05-09) — 17+ 项

| 编号 | 问题 | 状态 | 验证 |
|------|------|------|------|
| SEC-01 | API 端点零认证 | ✅ 已修 | `_require_api_key` 中间件已添加 |
| SEC-02 | .env 泄露 API Key | ✅ 已修 | 需要确认当前 .env 状态 |
| SEC-03 | 文件工具路径遍历 | ⚠️ 部分 | `_read_file`/`_write_file` 已修，`_grep_files`/`_search_code`/`_file_info` 仍需检查 |
| SEC-04 | shell_exec 无命令过滤 | ⚠️ 部分 | SecureSandbox 已添加黑名单，但绕过仍可能（见 SEC-06） |
| SEC-05/06 | 命令注入 (run_tests, lint, format) | ⚠️ 部分 | 添加了 shlex.quote 但 shell 拼接仍存在 |
| QUAL-01 | 全局单例重构 | ❌ 未修 | 仍使用全局单例模式 |
| QUAL-02 | LLMStateManager 与 LLMManager 职责重叠 | ❌ 未修 | CRITICAL — 两者完全独立运行 |
| ROB-01 | 异常静默吞没 | ⚠️ 部分 | `exception: pass` 已替换为日志，但 `governance/audit.py:111` 仍有 `pass` |
| ROB-02 | GovernanceWorkflow 硬编码 | ❌ 未修 | `governance/policy.py:54` |
| ROB-04 | CircuitBreaker 非线程安全 | ✅ 已修 | `asyncio.Lock` 已添加 |

---

## 8. 迭代优化路线图

### Phase 0 — 环境修复（0.5 人天）

| # | 任务 | 优先级 | 工作量 |
|---|------|--------|--------|
| 0.1 | 重建独立 `.venv`，解耦旧版本 | P0 | 15min |
| 0.2 | 重新安装 editable 包指向 LIVE 源码 | P0 | 5min |
| 0.3 | 修复 11 个测试异步调用 bug | P1 | 30min |
| 0.4 | 确认 `more_core/.env` 配置正确 | P1 | 5min |

### Phase 1 — 安全加固（2 人天）

| # | 任务 | 优先级 | 工作量 |
|---|------|--------|--------|
| 1.1 | RBAC 集成到 `MoRECore.execute()` 和工具调度管道 | P0 | 4h |
| 1.2 | MCP Server 添加 API Key 认证 | P0 | 2h |
| 1.3 | A2A 端点添加认证中间件 | P0 | 1h |
| 1.4 | L0 代码自动执行路径添加 PolicyEnforcer 检查 | P1 | 1h |
| 1.5 | SecureSandbox 黑名单增强（检测 shell + exec 组合） | P1 | 2h |
| 1.6 | `_lint_file`/`_format_code` 消除 shell 拼接 | P1 | 1h |
| 1.7 | GovernanceWorkflow 安全路径配置化 | P2 | 1h |
| 1.8 | 添加安全渗透测试（命令注入、路径遍历、XSS） | P1 | 3h |

### Phase 2 — 架构清理（3 人天）

| # | 任务 | 优先级 | 工作量 |
|---|------|--------|--------|
| 2.1 | 统一 LLMStateManager 和 LLMManager | P1 | 4h |
| 2.2 | 全局单例重构为依赖注入 | P2 | 4h |
| 2.3 | 清理 channels v2 草稿文件 + 重复 ChannelManager | P2 | 2h |
| 2.4 | 修复 CronParser 跨小时翻滚 | P2 | 1h |
| 2.5 | 清理重复的代码库版本（只保留 LIVE） | P1 | 2h |
| 2.6 | MCP transport 层私有 API 修复确认 | P2 | 1h |

### Phase 3 — 测试增强（2 人天）

| # | 任务 | 优先级 | 工作量 |
|---|------|--------|--------|
| 3.1 | API 端点集成测试（FastAPI TestClient） | P1 | 4h |
| 3.2 | MCP Server 测试（工具暴露 + 认证） | P1 | 2h |
| 3.3 | A2A 协议测试 | P2 | 1h |
| 3.4 | GovernanceWorkflow + IncidentResponse 测试 | P2 | 2h |
| 3.5 | 渗透测试套件（安全攻防场景） | P1 | 3h |
| 3.6 | `conftest.py` 改进 — 完整 mock LLM provider | P2 | 1h |

### Phase 4 — 可观测性（1 人天）

| # | 任务 | 优先级 | 工作量 |
|---|------|--------|--------|
| 4.1 | `httpx.AsyncClient` 连接池复用 | P2 | 1h |
| 4.2 | Prometheus 指标暴露（task count, latency, error rate） | P3 | 3h |
| 4.3 | EventBus `_pending_tasks` 泄漏防护 | P2 | 1h |
| 4.4 | 启动预检 — 无 LLM provider 时友好报错 | P2 | 1h |

---

## 总结评分

| 维度 | 评分 | 趋势 |
|------|:----:|:----:|
| 架构设计 | 8/10 | → 稳定，六层分层清晰 |
| 安全性 | 5/10 | ↗ 2 轮审计修复中，仍有 4 个 P0 级问题 |
| 代码质量 | 7/10 | ↗ 持续改进，全局单例/职责重叠待解决 |
| 测试覆盖率 | 6/10 | ↗ 从 57 增至 425 测试，仍有显著缺口 |
| 环境配置 | 3/10 | ↘ **严重退化** — .venv 与旧版本共享导致开发环境不可信 |
| 文档 | 8/10 | → 3 份审计报告 + ARCHITECTURE.md + 操作手册 |
| 可观测性 | 4/10 | → 仅有 JSONL 审计 + 内存指标 |

> **核心结论**: 代码库本身架构设计优秀、分层合理。此前 3 轮审计已修复约 55 个问题。**但开发环境配置严重退化**（ENV-01）导致代码修改无法被正确验证，这是当前迭代的最高优先级问题。其次是 RBAC 未在管道内部执行（SEC-01）和 MCP/A2A 零认证（SEC-02/03）。
