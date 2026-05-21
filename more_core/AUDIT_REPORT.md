# QNMing MoRE OS — 深度代码审计报告

> 审计范围: `more_core/more_core/` 全部模块 (~2800 LOC)
> 审计日期: 2026-05-02
> 审计方: Cascade (AI 辅助审计)

---

## 一、总体评价

架构设计良好——六层 (L0-L5) 分层清晰，关注点分离合理，插件系统遵循开闭原则。
但存在 **7 个高严重度问题** 和若干中/低严重度缺陷，需要逐一修复。

---

## 二、高严重度问题 (HIGH)

### H1. 🔴 EventBus stop() 不等待 pending handler 完成

**文件**: `core/event_bus.py:59-64`
**问题**: `stop()` 发送 `__shutdown__` 后只等待 `_runner` 退出，但 `_pending_tasks` 中可能仍有未完成的 handler。这些 fire-and-forget 任务可能在事件循环关闭时被取消，导致数据丢失（如审计日志未写入）。
**修复建议**:
```python
async def stop(self) -> None:
    self._running = False
    if self._runner is not None:
        await self._queue.put(Event(topic="__shutdown__"))
        await self._runner
        self._runner = None
    # 等待所有 pending handler 完成
    if self._pending_tasks:
        await asyncio.gather(*self._pending_tasks, return_exceptions=True)
```

### H2. 🔴 HyperAgent 直接写文件系统——路径遍历风险

**文件**: `metacognition/hyperagent.py:329-360`
**问题**: `_apply_modification` 直接通过 `Path(proposal.target)` 读写文件。虽然有 `_allowed_targets` 白名单，但：
1. 白名单是相对路径，攻击者可用 `../` 绕过匹配
2. `_allowed_targets` 可被 `set_allowed_targets()` 随意替换
3. 写入操作不经过沙箱

**修复建议**: 对 target 做 `Path.resolve()` 后验证其在项目目录内，且 `set_allowed_targets` 应只允许在 `__init__` 时配置。

### H3. 🔴 VersionControl 手工拼接 JSON，存在注入风险

**文件**: `metacognition/hyperagent.py:90-99`
**问题**: `_write_snapshot` 用 f-string 手动拼 JSON，如果 `file_path`、`description` 等字段含有引号或特殊字符，会产生损坏的 JSON 或注入。
**修复建议**: 使用 `json.dumps()` 序列化。

### H4. 🔴 SQLite 连接无线程安全保护

**文件**: `memory/sqlite_store.py`、`evolution/sqlite_archive.py`
**问题**: `sqlite3.connect()` 创建的连接默认只能在同一线程使用。如果在异步上下文中被多个协程并发调用（尤其 `search` + `put` 并发），可能抛出 `ProgrammingError`。
**修复建议**: 使用 `check_same_thread=False` 或切换到 `aiosqlite`。

### H5. 🔴 LLM 缓存不区分 stop 序列和 extra 参数

**文件**: `llm/manager.py:63-65`
**问题**: `_cache_key` 只用了 `system|prompt|temperature|max_tokens`，忽略了 `stop` 和 `extra`。相同 prompt 但不同 stop 序列的请求会错误命中缓存。
**修复建议**: 将 `stop` 和 `extra` 也纳入 cache key 计算。

### H6. 🔴 execute() 缺少 per-task 超时执行

**文件**: `runtime/orchestrator.py:155-235`
**问题**: `TaskRequest.timeout_s` 字段被定义但 **从未使用**。任务执行没有总时间限制，恶意或复杂查询可无限期阻塞系统。
**修复建议**: 用 `asyncio.wait_for(self._execute_pipeline(...), timeout=request.timeout_s)` 包裹。

### H7. 🔴 API CORS 全开放

**文件**: `api/server.py:54-59`
**问题**: `allow_origins=["*"]` + `allow_methods=["*"]` + `allow_headers=["*"]` 在生产环境中是严重的安全风险，任何网页都可以调用 API 执行任务。
**修复建议**: 从环境变量读取允许的 origins，默认仅 `localhost`。

---

## 三、中严重度问题 (MEDIUM)

### M1. 🟡 Ollama provider 未处理 ConnectError

**文件**: `llm/providers/ollama.py:32-39`
**问题**: 只捕获了 `httpx.ReadTimeout`，未处理 `httpx.ConnectError`（Ollama 未启动时）。异常会裸抛 httpx 内部类型，manager 虽能兜底但错误消息不友好。

### M2. 🟡 OpenAI provider stream 中 KeyError 风险

**文件**: `llm/providers/openai_compat.py:89`
**问题**: `obj["choices"][0].get("delta", {}).get("content")` — 如果 `choices` 为空列表，`[0]` 会抛 IndexError。SSE 流中某些事件（如心跳）可能不含 choices。

### M3. 🟡 EvolutionArchive 驱逐逻辑可能驱逐当前最佳 agent

**文件**: `evolution/archive.py:32-39`
**问题**: 满容量驱逐时，按 `created_at` 选最旧的，但最旧的可能就是当前 `best()` 所在。注释说"non-best"但代码未检查。
**修复建议**: 过滤掉 `best(branch)` 后再选最旧的。

### M4. 🟡 L0 tool-call 循环缺失上下文累积

**文件**: `layers/l0_execution.py:79-91`
**问题**: 每轮工具调用的 followup prompt 只包含当前轮工具结果，丢失了原始 query 和前几轮对话上下文。多轮工具调用将越来越"失忆"。

### M5. 🟡 L0 自动执行 LLM 生成的代码存在安全风险

**文件**: `layers/l0_execution.py:94-101`
**问题**: 对于 `CODE_GENERATION`/`CODE_DEBUGGING` 任务，L0 自动提取并执行 LLM 输出中的 Python 代码。虽然走沙箱，但：
1. 执行发生在 L3 symbolic 检查 **之前**（pipeline 是 L4→L3→L1→L0，代码在 L0 生成并执行，L3 只事先检查 request）
2. 基线沙箱 (`SubprocessSandbox`) 明确声明不是安全边界

### M6. 🟡 `preexec_fn` 在 asyncio 子进程中已弃用

**文件**: `sandbox/subprocess_sandbox.py:69`
**问题**: Python 3.12+ 文档建议在异步上下文中不使用 `preexec_fn`，因为它在 fork 后、exec 前执行，可能导致死锁。

### M7. 🟡 Calibrator 自引用循环

**文件**: `metacognition/metacognition.py:27-33`
**问题**: `calibrate()` 将 `avg_conf` 同时作为 `confidence` 和 `accuracy` 传给 `observe()`，导致 alignment 永远为 1.0。校准机制形同虚设。
**修复建议**: accuracy 应来自外部反馈（如工具执行结果、用户评分），不应等于 confidence 本身。

### M8. 🟡 audit.py 并发写入可能交错

**文件**: `governance/audit.py:28-30`
**问题**: `write()` 每次打开/关闭文件，多个协程并发写入时可能交错。虽然单行 JSON + `os.linesep` 通常原子，但 `open("a")` 不保证跨平台原子性。
**修复建议**: 使用 `logging` 或文件锁。

---

## 四、低严重度问题 (LOW)

### L1. `LLMProviderConfig.timeout_s` 默认 60 与 OllamaProvider 默认 120 不一致

**文件**: `core/config.py:25` vs `llm/providers/ollama.py:15`
**影响**: 从 config 构建的 provider 实际用 60s（config 覆盖了 provider 默认值），冷启动仍可能超时。

### L2. `TaskRequestPayload.context` 使用 mutable default `{}`

**文件**: `api/server.py:30`
**影响**: Pydantic v2 实际能安全处理此情况，但代码风格上应使用 `Field(default_factory=dict)`。

### L3. `_PIPELINES` router 硬编码

**文件**: `router/layer_router.py:23-35`
**影响**: 不可通过配置或插件扩展管道模板，违反了系统的"插件可扩展"设计原则。

### L4. `_publish_status_change` 是空方法

**文件**: `metacognition/hyperagent.py:437-438`
**影响**: proposal 状态变更不发送事件，外部观察者无法订阅。

### L5. `datetime.utcnow()` 已弃用

**文件**: `metacognition/hyperagent.py:55,64`
**影响**: Python 3.12+ 建议使用 `datetime.now(datetime.UTC)`。

### L6. `Layer.__init__` 基类缺少 `__init__`

**文件**: `layers/base.py:38-44`
**影响**: `SymbolicLayer.__init__` 调用 `super().__init__()` 但 `Layer` 是 ABC 无 `__init__`，依赖 Python 默认 `object.__init__` 隐式工作，但不够显式。

### L7. 测试覆盖率不足

**目录**: `tests/`
**影响**: 14 个测试文件但缺少 L0 执行层（LLM + tool call 循环）、API server、多 provider fallback 的测试。

---

## 五、架构建议

| 领域 | 建议 |
|------|------|
| **任务超时** | `execute()` 应包裹 `asyncio.wait_for`，使用 `TaskRequest.timeout_s` |
| **LLM 重试** | manager fallback 只做 provider 切换，缺少同 provider 重试 + 指数退避 |
| **结构化输出** | L0 工具调用依赖正则解析 XML-style tags，应支持 OpenAI function calling native 格式 |
| **可观测性** | 缺少 metrics 导出（Prometheus/OpenTelemetry），仅有 JSONL 审计 |
| **配置验证** | `Settings.from_env()` 对 `int()` 转换无错误处理（如 `MORE_SANDBOX_TIMEOUT=abc` 会崩溃） |
| **Graceful degradation** | 无 LLM provider 时 `execute()` 直接崩溃，应该在启动时预检并给出友好错误 |

---

## 六、已修复的问题（本次审计前修复）

| 问题 | 修复 |
|------|------|
| 缺少 `__main__.py` | 已创建内外两层 `__main__.py` |
| 插件管理器混淆 pip/plugin 依赖 | 已添加 `re.search` 区分逻辑 |
| CLI `query` 参数不兼容 `--query` | 已改为 flag |
| Ollama ReadTimeout 空消息 | 已添加捕获 + 友好提示 |
| `.venv` 指向已删除路径 | 已重建 |

---

## 七、修复状态 (2026-05-02 已全部完成)

| 优先级 | 编号 | 问题 | 状态 |
|--------|------|------|------|
| P0 | H2 | HyperAgent 路径遍历 | ✅ 已修复 — 添加 project_root + resolve() 校验 |
| P0 | H3 | VersionControl JSON 注入 | ✅ 已修复 — 改用 json.dumps() |
| P0 | H7 | API CORS 全开放 | ✅ 已修复 — 从 MORE_CORS_ORIGINS 读取，默认 localhost |
| P1 | H1 | EventBus 不等待 pending handler | ✅ 已修复 — stop() 增加 gather + clear |
| P1 | H4 | SQLite 线程安全 | ✅ 已修复 — check_same_thread=False |
| P1 | H6 | execute() 无超时 | ✅ 已修复 — asyncio.wait_for + _run_pipeline 提取 |
| P2 | H5 | LLM 缓存 key 不完整 | ✅ 已修复 — 纳入 stop + extra |
| P2 | M3 | Archive 驱逐最佳 agent | ✅ 已修复 — 排除 best() 后再选驱逐对象 |
| P2 | M5 | L0 代码执行在 L3 检查之前 | ✅ 已修复 — 执行前调用 L3 rule_engine 检查 |
| P2 | M7 | Calibrator 自引用 | ✅ 已修复 — accuracy 改用外部信号 |
| P2 | M1 | Ollama 未处理 ConnectError | ✅ 已修复 |
| P2 | M2 | OpenAI stream IndexError | ✅ 已修复 — guard empty choices |
| P2 | M4 | L0 tool-call 上下文丢失 | ✅ 已修复 — followup 含原始 query |
| P2 | M6 | preexec_fn 弃用 | ✅ 已修复 — 移除，依赖 timeout + cgroup |
| P2 | M8 | audit 并发写入 | ✅ 已修复 — threading.Lock |
| LOW | L1 | timeout_s 默认值不一致 | ✅ 已修复 — config 对齐 120s |
| LOW | L2 | mutable default {} | ✅ 已修复 — Field(default_factory=dict) |
| LOW | L4 | _publish_status_change 空方法 | ✅ 已修复 — 接入 event_bus |
| LOW | L5 | datetime.utcnow() 弃用 | ✅ 已修复 — datetime.now(timezone.utc) |
| LOW | L6 | Layer 基类缺 __init__ | ✅ 已修复 |
| LOW | L3 | router 硬编码 | ✅ 已修复 — 可配置 custom_pipelines + 插件 register/unregister API |
| LOW | L7 | 测试覆盖率不足 | ✅ 已修复 — 新增 38 个测试 (L0、API、fallback、router 扩展、回归) |

**验证**: 95 个测试全部通过 (57→95)，CLI 端到端运行正常。
