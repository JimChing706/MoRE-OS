# QNMing MoRE OS — 综合代码审计报告

> **审计日期**: 2025-04-27  
> **审计范围**: 全仓库 (`more_core/`, `app/`, `plugins/`, 构建/部署配置)  
> **代码版本**: 0.3.0

---

## 一、项目总览

| 维度 | 现状 |
|------|------|
| **核心内核** (`more_core/`) | Python ≥3.10，六层架构 L0–L5，~60 个源文件，~4500 行 |
| **Dashboard 前端** (`app/src/`) | React 19 + TypeScript + Vite 7 + shadcn/ui + Tailwind |
| **Dashboard BFF 服务** (`app/server/`) | FastAPI (独立进程)，LM Studio / OpenAI / Anthropic / Ollama |
| **内核 API 服务** (`more_core/api/`) | FastAPI，与 `MoRECore` 深度集成 |
| **插件** (`plugins/`) | 麻将行业 Pack (骨架)；SDK + scaffold 已就绪 |
| **测试** (`more_core/tests/`) | 13 个测试文件，覆盖核心路由/运行时/规则引擎/持久化/工具/沙箱/进化 |
| **部署** | Dockerfile (前端) + docker-compose (Redis/Prometheus/Grafana) |

### 整体评价

`more_core/` 是一套**架构清晰、领域无关、可扩展**的 Agent OS 内核。类型定义 (Pydantic)、异常层次、事件总线、插件系统、规则引擎等基础设施完备度较高，已达到 Beta 品质。`app/server/` (BFF) 是早期 MVP 遗产，质量与 `more_core/` 差距明显。

---

## 二、架构设计审计

### 2.1 优点

1. **六层分离清晰** — `Layer` 抽象基类 + `LayerRouter` 管线式调度，L0–L5 各层职责明确。
2. **领域无关** — 核心不含麻将/游戏代码，行业逻辑完全推入 `plugins/`。
3. **Feature gate 设计** — `enable_evolution`、`enable_metacognition`、`enable_symbolic` 三个开关控制高风险能力，默认关闭。
4. **双层治理** — `PolicyEnforcer` 前置校验 + `RuleEngine` 前向链推理 + `AuditLogger` JSONL 审计链。
5. **可扩展点丰富** — Layer / Plugin / Tool / Benchmark / LLMProvider / OntologyEntity 均可扩展。
6. **持久化可插拔** — 内存 ↔ SQLite 通过环境变量无代码切换。

### 2.2 问题

| # | 严重度 | 问题 | 位置 |
|---|--------|------|------|
| A1 | ⚠️ 中 | **`app/server/` 与 `more_core/` 并行存在两套独立后端**，路由表、类型定义、LLM 调用逻辑重复，且 BFF 层大量硬编码伪数据（`asyncio.sleep(0.1)`、假 token 数、假 confidence） | `app/server/src/main.py` |
| A2 | ⚠️ 中 | **BFF 层未使用 `more_core`** — 本应作为薄代理转发到 `more_core` API，实际自行实现了第二套 task pipeline | `app/server/src/main.py:104-184` |
| A3 | 🔵 低 | `SymbolicLayer.__init__` 调用 `super().__init__()` 但 `Layer` 是 ABC 且无 `__init__`，虽然 Python 不报错但不规范 | `more_core/layers/l3_symbolic.py:25` |

---

## 三、安全性审计

### 3.1 🔴 严重 — API 密钥泄露

**`app/server/.env.example` 包含真实 OpenAI API Key：**

```
OPENAI_API_KEY=sk-proj-****REDACTED****
```

> 这是一个格式完全匹配 OpenAI `sk-proj-*` 的真实密钥，已提交到版本库。**必须立即撤销此密钥并替换为占位符**。

### 3.2 ⚠️ 中 — Grafana 默认管理密码

`app/docker-compose.yml` 中硬编码了 `GF_SECURITY_ADMIN_PASSWORD=morev3admin`。生产部署应使用 secret 管理。

### 3.3 ⚠️ 中 — CORS 全开

`more_core/api/server.py` 和 `app/server/src/main.py` 都设置了 `allow_origins=["*"]`。开发阶段可接受，生产部署需收紧。

### 3.4 ⚠️ 中 — 沙箱非安全边界

`SubprocessSandbox` 文档明确声明"不是安全边界"，仅通过 `resource.setrlimit` 做内存限制。`LinuxSandbox` 使用 cgroup v2 + unshare，但需要 root 权限。当前没有 seccomp / gVisor / WASM 隔离层。

### 3.5 🔵 低 — `run_python` 环境变量泄漏

`SubprocessSandbox.run_python` 传入 `env={"PATH": os.environ.get("PATH", "")}`，仅暴露 PATH，但更安全的做法是使用一个完全空的或白名单环境。

### 3.6 🔵 低 — 审计日志文件模式

`AuditLogger` 以同步追加写入 JSONL 文件。高并发下可能存在写竞争（虽然 Python GIL 缓解了部分问题）。建议后续迁移到异步写入或数据库后端。

---

## 四、`more_core/` 代码质量审计

### 4.1 类型系统与数据模型 ✅ 良好

- 全面使用 Pydantic v2 `BaseModel` + `frozen` dataclass。
- `__init__.py` 导出清晰，`__all__` 完整。
- 错误层次合理：`MoREError` → `PluginError` / `LLMError` / `SandboxError` / `GovernanceError` / `RoutingError`。

### 4.2 运行时编排 (`orchestrator.py`) ✅ 良好

- 生命周期管理完善（`start` / `stop`）。
- 异常处理三层：`GovernanceError` → `REJECTED`，`MoREError` → `FAILED`，`Exception` → `FAILED` + 日志。
- 性能度量完整（时间、token、层转换次数）。

### 4.3 问题清单

| # | 严重度 | 问题 | 位置 | 建议 |
|---|--------|------|------|------|
| C1 | ⚠️ 中 | `execute()` 管线中只取 L0 的 output 作为最终输出。如果 L0 不在管线中（理论上 `RoutingError` 会阻止），上层结果被丢弃 | `orchestrator.py:179` | 考虑收集所有层 output 到一个 dict |
| C2 | ⚠️ 中 | `EventBus._safe_call` 吞了所有异常只打 `debug` 级日志。关键事件处理器失败时调用方完全无感知 | `event_bus.py:84` | 对关键 topic 至少记 `warning` |
| C3 | 🔵 低 | `EvolutionArchive.add()` 驱逐策略按 `created_at` 淘汰最旧条目，但可能驱逐当前 best agent | `archive.py:34-39` | 驱逐前检查是否为 best |
| C4 | 🔵 低 | `LayerRouter.route()` 显式目标路由逻辑 `idx = int(request.target_layer.value[1])` 假设 LayerId 格式永远为 "L{digit}"，未来扩展为两位数时会错误 | `layer_router.py:45` | 用 `LayerId` 枚举值 mapping |
| C5 | 🔵 低 | `Calibrator.observe()` 始终以 confidence ≈ accuracy 调用（`metacognition.py:26`），导致 alignment 恒等于 ~1.0，HyperAgent 永远不触发 | `metacognition.py:26` | 引入真实 ground-truth 反馈信号 |
| C6 | 🔵 低 | `SQLiteMemoryStore` 继承 `MemoryStore` 并调用 `super().put()`，数据同时存在内存 deque 和 SQLite，但 `list()` 只查 SQLite，两份数据不同步 | `sqlite_store.py:49-50` | 仅写 SQLite，去掉 super().put() |
| C7 | 🔵 低 | `LLMManager._cache_key` 未包含 `stop` tokens 和 `extra` 参数，不同请求可能命中同一缓存 | `llm/manager.py:64` | 将所有语义相关字段纳入 hash |
| C8 | 🔵 低 | httpx client 在每次 LLM 调用中重新创建 (`async with httpx.AsyncClient`)，开销较大 | `providers/*.py` | 使用单例 client 并在 health 中重用 |

### 4.4 规则引擎 ✅ 优秀

前向链推理引擎实现完备：优先级排序、冲突解析、halt、assert/retract/annotate/violation 动作。内置 3 条治理规则（查询长度、未授权进化、危险代码检测）。测试覆盖全面。

### 4.5 插件系统 ✅ 良好

- `plugin.json` 清单驱动、DFS 依赖解析。
- SDK 提供 `PluginBase` 便捷基类 + `scaffold_plugin()` 脚手架。
- `PluginInterface` 使用 `runtime_checkable Protocol`。

#### 插件问题

| # | 问题 |
|---|------|
| P1 | `mahjong-industry-pack/plugin.json` 使用 `"entry": "main.Plugin"` 但 `PluginManager._read_manifest` 读取的是 `"entry_point"` 字段。**manifest 字段名不匹配**，discover 时 `entry_point` 会回退到默认值 `"main"`，恰好能工作但不正确。 |
| P2 | `Plugin.capabilities()` 返回 `list[str]` 但 `PluginInterface` 协议定义返回 `dict[str, Any]`，类型不匹配。 |
| P3 | 插件的 `activate(context)` 接受 `Any` 类型而非 `PluginContext`，绕过了类型检查。 |

---

## 五、`app/server/` (BFF) 代码审计

### 5.1 🔴 严重 — 架构性问题

BFF (`app/server/src/main.py`, 450 行) 是早期 MVP 的"影子后端"，**完全未集成 `more_core`**：

1. **伪数据管线** — `execute_task_with_layers()` 不调用任何真实层逻辑，只做 `asyncio.sleep(0.1)` 后拼接假 reasoning chain（硬编码 token 数、confidence 值）。
2. **重复类型定义** — `TaskRequest`, `ReasoningStep`, `TaskResponse` 在 BFF 和 `more_core` 中各定义一份，字段名称和语义有差异。
3. **重复路由表** — `determine_routing_layers()` 在 BFF 中硬编码了第二份路由映射，与 `more_core/router/layer_router.py` 不同步（例如 `multi_agent_orchestration` BFF 缺少 L4，`code_debugging` BFF 含 L2 而 `more_core` 不含）。
4. **`StreamingResponse` 在文件底部 import** — `from starlette.responses import StreamingResponse` 在 line 335，违反 import 规范。

### 5.2 ⚠️ 中 — 状态管理问题

- **`task_history` 全局 list** — 无并发锁保护，WebSocket 和 HTTP 端点同时写入可能数据竞争。
- **Redis 排序逻辑错误** — `load_task_history_from_redis` 按 `total_duration` 降序排序，语义上应按时间戳排序。
- **Redis keys 扫描** — 使用 `KEYS` 命令，生产环境应改用 `SCAN`。

### 5.3 ⚠️ 中 — `llm_service.py` 代码异味

- `sys.path.insert(0, ...)` 是脆弱的路径 hack。
- `_stream_openai` 中 `yield await self._fallback_response(query)["output"]` 对 coroutine 取下标会报错（`await` 返回 dict 后再取 `["output"]` 可以，但 `yield` 一个 `await` 的结果在语法上正确，逻辑上有风险）。
- 缺少 `__all__` 或显式模块接口。

---

## 六、前端代码审计

### 6.1 ✅ 良好

- 使用 React 19 + TypeScript 5.9 + Vite 7 + shadcn/ui + Tailwind，技术栈现代。
- 组件拆分合理：`SystemDashboard`, `TaskPanel`, `LayerVisualizer`, `EvolutionBrowser`, `MemoryPanel`, `SafetyPanel`。
- 路由配置 (`react-router` v7)。

### 6.2 问题

| # | 严重度 | 问题 |
|---|--------|------|
| F1 | 🔵 低 | `App.tsx` 仍保留 `/mahjong` 路由，属于领域耦合残留。 |
| F2 | 🔵 低 | 前端连接 BFF (`app/server`)，而非 `more_core` API。需要对接统一后端后更新 API base URL。 |
| F3 | 🔵 低 | `vite.config.ts` 使用 `kimi-plugin-inspect-react`，这是一个第三方调试插件，生产构建应移除。 |
| F4 | 🔵 低 | `package.json` 同时引入 `react-router` 和 `react-router-dom`，后者在 v7 中已合并。 |

---

## 七、测试审计

### 7.1 覆盖面

| 模块 | 测试文件 | 覆盖状态 |
|------|----------|----------|
| 运行时 / 编排 | `test_runtime.py` | ✅ NLP 执行、治理阻断、内存存取 |
| 路由器 | `test_router.py` | ✅ 默认管线、L5 启用、L2 启用 |
| 事件总线 | `test_event_bus.py` | ✅ 发布/订阅 |
| 规则引擎 | `test_rule_engine.py` | ✅ 全面 (10 个用例) |
| 持久化 | `test_persistence.py` | ✅ SQLite 记忆 + 进化归档 |
| 工具注册 | `test_tools.py` | ✅ 注册/调用/schema |
| 沙箱 | `test_sandbox.py` | ✅ stdout / 超时 |
| DGM 进化 | `test_benchmark.py` | ✅ 基准评估 + DGM 循环 |
| 插件 SDK | `test_plugin_sdk.py` | ✅ scaffold / metadata |
| 服务注册 | `test_service_registry.py` | ✅ 注册/发现 |
| Linux 沙箱 | `test_linux_sandbox.py` | ✅ 兼容性回退 |
| L0 执行层 | ❌ 无 | 缺少 tool-call 解析、auto code-exec 的单元测试 |
| L3 符号层 | ❌ 无 | 缺少 SymbolicLayer 集成测试 |
| L4/L5 | ❌ 无 | 缺少认知/元认知层测试 |
| API 端点 | ❌ 无 | 缺少 FastAPI TestClient 测试 |
| BFF 服务 | ❌ 无 | `app/server/` 零测试 |
| 前端 | ❌ 无 | 无任何前端测试 |

### 7.2 测试质量

- `conftest.py` 的 `FakeLLM` mock 设计良好，测试不依赖外部服务。
- `pytest-asyncio` 配置 `asyncio_mode = "auto"`，异步测试无需手动标记。
- 缺少 coverage 报告的 CI 集成。

---

## 八、构建/部署审计

### 8.1 ✅ Makefile 完整

提供 `install`, `test`, `lint`, `format`, `typecheck`, `serve`, `build`, `clean` 等目标。

### 8.2 问题

| # | 问题 |
|---|------|
| D1 | `docker-compose.yml` 未包含 `app/server/` 后端服务的容器定义，只有前端 + Redis + Prometheus + Grafana。 |
| D2 | `app/server/requirements.txt` 版本锁定不一致：`fastapi==0.104.1` (旧) vs `more_core` 要求 `fastapi>=0.110`。 |
| D3 | 无 CI/CD 配置（无 `.github/workflows/`, 无 `.gitlab-ci.yml`）。 |
| D4 | `pyproject.toml` 使用 `dynamic = ["version"]` 通过 `more_core.version.__version__` 读取，但 `version.py` 不在 git 控制的文件列表中可能导致 `sdist` 构建失败（需验证）。 |

---

## 九、一致性审计

### 9.1 两套后端路由表不一致

| 任务类型 | `more_core` `LayerRouter` | `app/server` BFF |
|----------|--------------------------|------------------|
| `multi_agent_orchestration` | L4 → L1 → L0 | L1 → L0（缺 L4） |
| `code_debugging` | L4 → L3 → L1 → L0 | L4 → L3 → L2 → L0（多 L2，缺 L1） |
| `code_review` | L4 → L3 → L1 → L0 | L4 → L3 → L2 → L0（多 L2，缺 L1） |

### 9.2 插件 manifest 字段不一致

`mahjong-industry-pack/plugin.json` 使用 `"entry"` 和 `"more_os_version"`，但 `PluginManager._read_manifest` 期望 `"entry_point"` 和 `"min_core_version"`。

---

## 十、综合建议（按优先级排序）

### 🔴 P0 — 立即修复

1. **撤销泄露的 OpenAI API Key** — 在 OpenAI 后台立即 revoke `sk-proj-a3qep9...`，将 `.env.example` 中替换为 `your-openai-api-key-here`。
2. **确认 Git 历史已清理** — 即使修改文件，密钥仍在 git history 中。建议使用 `git filter-branch` 或 BFG Repo Cleaner 清除。

### 🟡 P1 — 短期优化（1-2 周）

3. **统一后端** — 将 `app/server/` BFF 改造为 `more_core` API 的薄代理，移除重复的 pipeline 模拟逻辑。
4. **修复插件 manifest 字段名** — `plugin.json` 的 `"entry"` → `"entry_point"`，`"more_os_version"` → `"min_core_version"`。
5. **修复 `Plugin.capabilities()` 返回类型** — 与 `PluginInterface` 协议保持一致 (`dict[str, Any]`)。
6. **修复 BFF 的 `StreamingResponse` import** — 移到文件顶部。
7. **对齐 `app/server/requirements.txt`** — 升级 `fastapi` 等依赖版本。

### 🔵 P2 — 中期改进（1-3 月）

8. **补充测试** — L0 tool-call 解析、L3 集成、API 端点、BFF 端到端。
9. **添加 CI/CD** — GitHub Actions: lint + typecheck + test + coverage。
10. **EventBus 异常处理** — 关键 topic handler 失败时至少 `warning` 级别日志。
11. **SQLiteMemoryStore 去重** — 去掉 `super().put()`，避免内存/SQLite 双写不同步。
12. **LLM 缓存键完整性** — 将 `stop` 和 `extra` 纳入 hash。
13. **httpx client 复用** — LLM provider 使用单例 AsyncClient。
14. **收紧 CORS** — 生产环境限定 allow_origins。
15. **Grafana 密码外置** — 使用 Docker secrets 或环境变量注入。

### ⚪ P3 — 长期规划

16. **前端测试** — 添加 Vitest + React Testing Library。
17. **审计日志异步化** — 高并发场景下避免文件写阻塞。
18. **沙箱增强** — 接入 gVisor / Firecracker / WASM 运行时。
19. **元认知校准真实信号** — 引入用户反馈或下游评估作为 accuracy 来源。
20. **移除 `kimi-plugin-inspect-react`** — 生产构建不需要调试插件。

---

## 十一、代码指标摘要

| 指标 | 值 |
|------|----|
| `more_core/` Python 源文件数 | ~40 |
| `more_core/` 代码行数 (不含测试) | ~4500 |
| `more_core/tests/` 测试文件数 | 13 |
| `app/src/` TypeScript/TSX 文件数 | ~70 |
| `app/server/src/` Python 文件数 | 5 |
| `app/server/src/` 代码行数 | ~1200 |
| 已发现安全问题 | 1 严重, 2 中等, 2 低 |
| 已发现功能缺陷 | 2 中等, 8 低 |
| 已发现一致性问题 | 4 项 |
| 测试覆盖空白 | 6 个模块无测试 |

---

*报告结束。建议按 P0 → P1 → P2 → P3 优先级顺序依次处理。*
