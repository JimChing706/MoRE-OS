# QNMing MoRE OS — 系统性代码审计报告

**审计日期**: 2025-05-09  
**审计范围**: `more_core/` (Python核心引擎) + `app/server/` (BFF网关)  
**技术栈**: Python 3.12 / FastAPI / Pydantic / httpx / asyncio  

---

## 总览评分

| 维度 | 评分 | 等级 |
|------|------|------|
| 安全性 | 5/10 | **需紧急修复** |
| 性能 | 7/10 | 良好 |
| 可维护性 | 8/10 | 良好 |
| 鲁棒性 | 6/10 | 需改进 |
| 测试完备性 | 6/10 | 需补充 |

---

## 1. 安全性审计 (Security) — 严重级别: HIGH

### SEC-01 [P0_FATAL] API 端点零认证

**文件**: `more_core/api/server.py` 全部端点  
**问题**: 所有 API 端点（包括 `/api/v1/tasks/execute`、`/api/v1/llm/state/update`、`/api/v1/incidents/{id}/resolve`）**完全没有身份认证和授权机制**。任何人只要能访问网络即可：
- 执行任意任务（含 `shell_exec`、`python_exec`）
- 动态修改 LLM 参数（provider、model、endpoint）
- 解决安全事件（清除事件记录）
- 查看全部系统内部状态

**修复建议**:
```python
# 最小方案：添加 API Key 中间件
from fastapi import Depends, HTTPException, Header

async def verify_api_key(authorization: str = Header(...)):
    expected = os.getenv("MORE_API_KEY")
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")

# 对写操作端点添加依赖
@app.post("/api/v1/tasks/execute", dependencies=[Depends(verify_api_key)])
```

---

### SEC-02 [P0_FATAL] .env.example 泄露真实 API Key

**文件**: `app/server/.env.example:15`  
**问题**: OpenAI API Key 以 `sk-proj-a3q******aaz-...` 形式存储在版本控制中。虽然部分已星号遮挡，但格式暴露了前缀和结构，且历史提交中可能包含完整密钥。

**修复建议**:
- 立即轮换（revoke）该 OpenAI API Key
- 将 `.env.example` 中的值替换为 `your-openai-api-key-here`
- 运行 `git filter-branch` 或 BFG 清除历史中的密钥

---

### SEC-03 [P1_CRITICAL] 文件操作工具缺少路径遍历防御

**文件**: `more_core/tools/builtins.py`  
**问题**:
- `_file_info` (L120)、`_create_directory` (L146)、`_delete_file` (L163) 均**缺少 `target.relative_to(root)` 路径遍历检查**，只有 `_read_file` 和 `_write_file` 有此防御
- `_delete_file` 支持 `recursive=True` 的 `shutil.rmtree`，配合路径遍历可删除任意目录
- `_grep_files` 和 `_search_code` 无路径边界验证

**影响**: 攻击者通过 `path=../../etc/passwd` 可读取系统文件，`path=../../` + `recursive=True` 可递归删除文件系统。

---

### SEC-04 [P1_CRITICAL] shell_exec 无命令过滤

**文件**: `more_core/tools/builtins.py:35-45`  
**问题**: `_shell_exec` 直接将用户输入传递给 `core.sandbox.run(command)`，虽然有 sandbox 超时限制，但在非 Linux 平台无 cgroup/namespace 隔离，等同于直接执行任意 shell 命令。

**修复建议**:
- 添加命令白名单/黑名单过滤
- 对 macOS/Windows 平台增加显式警告或禁用

---

### SEC-05 [P2_MAJOR] run_tests 工具存在命令注入

**文件**: `more_core/tools/builtins.py:399-402`  
```python
cmd = f"pytest {test_path} -p no:cacheprovider"
cmd += f" --tb=short -k \"{pattern}\""
```
**问题**: `test_path` 和 `pattern` 参数通过字符串拼接进入 shell 命令，可注入任意 shell 语句。例如 `pattern="; rm -rf /"` 即可攻击。

---

### SEC-06 [P2_MAJOR] lint/format 工具同样存在命令注入

**文件**: `more_core/tools/builtins.py:438, 478`  
`file_path` 直接拼接到 f-string shell 命令中，未做任何转义。

---

### SEC-07 [P2_MAJOR] LLM state/update 端点缺少值校验

**文件**: `more_core/api/server.py:159-181`  
**问题**: `/api/v1/llm/state/update` 虽有 `allowed_keys` 白名单，但对值**无类型和范围校验**。攻击者可以：
- 设置 `temperature=-999` 或 `max_tokens=9999999`
- 设置 `lmstudio_endpoint` 指向恶意服务器（SSRF）
- 设置 `provider` 为无效值

---

### SEC-08 [P3_MINOR] CORS 配置过于宽泛

**文件**: `more_core/api/server.py:56-63`  
默认 `allow_credentials` 为 False（合理），但生产环境应通过环境变量限制更严格的 origins，当前默认值 `http://localhost:3000` 仅适合开发。

---

## 2. 性能审计 (Performance)

### PERF-01 [P2_MAJOR] RequestCache O(n) 驱逐策略

**文件**: `more_core/optimization.py:53-54, 67`  
```python
self._access_order.remove(key)  # O(n) 列表扫描
```
**问题**: `_access_order` 使用 `list`，`remove()` 操作为 O(n)。每次缓存命中/驱逐都需要线性扫描。当 `max_size=1000` 时还可接受，但随着规模增长会成为瓶颈。

**修复建议**: 使用 `collections.OrderedDict`（如 `LLMManager._LRU` 已正确实现）。

---

### PERF-02 [P3_MINOR] MemoryStore.search 全表扫描

**文件**: `more_core/memory/store.py:50-65`  
**问题**: `search()` 对全部条目做 `sorted()` + casefold + NFKC normalize，每次搜索 O(n log n)。在 capacity=2048 时可接受，但语义搜索应引入向量索引。

---

### PERF-03 [P3_MINOR] httpx.AsyncClient 未复用

**文件**: `more_core/llm/providers/openai_compat.py:50, 70`  
**问题**: 每次 `generate()` 和 `stream()` 调用都创建新的 `httpx.AsyncClient`，无法复用 TCP 连接和连接池。

**修复建议**: 在 provider 构造时创建持久 client，在 shutdown 时关闭。

---

### PERF-04 [P2_MAJOR] 事件监听器泄漏

**文件**: `app/server/src/main.py:258`  
```python
core.event_bus.subscribe("layer.completed", _on_layer_completed)
```
**问题**: 每次 `execute_task_real` 调用都订阅新的 listener 但**从不取消订阅**，导致 EventBus 监听器无限增长（内存泄漏）。

---

## 3. 代码质量与可维护性 (Quality)

### QUAL-01 [P2_MAJOR] 全局可变单例状态

**文件**:
- `more_core/incident_response.py:238` — `_global_incident_manager`
- `more_core/llm/state_manager.py:204` — `_global_llm_state`
- `more_core/zen_rules.py:225` — `_enforcer`
- `more_core/metrics.py` — `get_collector()`

**问题**: 4+ 个模块使用全局可变单例。这些与 `MoRECore` 实例之间存在隐式耦合：
- `server.py` 通过 `get_llm_state_manager()` 获取的状态与 `MoRECore.llm` 完全独立
- 多实例测试或热重载时状态会互相污染
- 单例 `__new__` + `_initialized` 的双重检查锁实现正确，但 `_initialized` 属性不是 class-level 声明

**修复建议**: 将全局单例注入到 `MoRECore` 构造中，通过依赖注入传递。

---

### QUAL-02 [P3_MINOR] LLMStateManager 与 LLMManager 职责重叠

`LLMStateManager` 管理调用参数，`LLMManager` 管理 provider 路由和缓存。但 `LLMStateManager` 的状态（provider/model/temperature）**从未被 `LLMManager.generate()` 消费**，两者完全独立运行。前端通过 `/api/v1/llm/state/update` 修改的参数对实际 LLM 调用无影响。

---

### QUAL-03 [P3_MINOR] 未使用的导入

**文件**: `more_core/tools/builtins.py:8` — `import fnmatch`（未使用）  
**文件**: `more_core/tools/builtins.py:12` — `import subprocess`（未使用）

---

### QUAL-04 [P3_MINOR] _run_tests 中 timeout 参数 API 不匹配

**文件**: `more_core/tools/builtins.py:405`  
```python
sbx = await core.sandbox.run(cmd, timeout=300)
```
**问题**: `SubprocessSandbox.run()` 签名中无 `timeout` 关键字参数，超时由构造时的 `_timeout` 控制。传入 `timeout=300` 会被 `**kwargs` 静默忽略或报错。

---

## 4. 鲁棒性与错误处理 (Robustness)

### ROB-01 [P1_CRITICAL] 异常被静默吞没

多处关键路径存在 bare `except Exception: pass`:

| 文件 | 行 | 影响 |
|------|-----|------|
| `zen_rules.py:150-151` | `check_fn` 异常被吞 | 规则检查永远不会触发违规 |
| `zen_rules.py:174` | 回调异常被吞 | 违规通知静默失败 |
| `state_manager.py:92-93` | 状态回调异常被吞 | 状态变更通知丢失 |
| `incident_response.py:145-146` | 升级回调异常仅 log | 可接受但应记录更多上下文 |

**修复建议**: 至少添加 `logger.exception()` 日志记录。

---

### ROB-02 [P2_MAJOR] GovernanceWorkflow 硬编码安全路径

**文件**: `more_core/governance/policy.py:54`  
```python
safe_targets = ["more_core/layers/l4_cognition.py", "more_core/router/layer_router.py"]
```
**问题**: 自动审批的 "安全路径" 硬编码为特定文件名，这意味着：
- 文件重命名会悄悄破坏自动审批逻辑
- 安全策略无法通过配置调整

---

### ROB-03 [P2_MAJOR] RuleSeverity 枚举值不受验证

**文件**: `more_core/api/server.py:241`  
```python
sev = RuleSeverity(severity) if severity else None
```
**问题**: 如果用户传入无效的 `severity` 字符串，`RuleSeverity(severity)` 会抛出 `ValueError`，导致 500 错误。同样的问题存在于 `Severity` 枚举（L287）。

---

### ROB-04 [P2_MAJOR] CircuitBreaker 非线程安全

**文件**: `more_core/optimization.py:140-197`  
**问题**: `CircuitBreaker` 的状态修改（`_on_success`、`_on_failure`）无锁保护。在并发环境下 `_state.failures` 计数可能不准确，导致断路器行为异常。

---

### ROB-05 [P3_MINOR] SubprocessSandbox.run 使用已弃用的事件循环 API

**文件**: `more_core/sandbox/subprocess_sandbox.py:60`  
```python
start = asyncio.get_event_loop().time()
```
**问题**: Python 3.12+ 中 `asyncio.get_event_loop()` 在没有运行中循环时会发出弃用警告。应改用 `asyncio.get_running_loop().time()`。

---

## 5. 测试完备性 (Test Coverage)

### TEST-01 当前测试概况

- **测试文件数**: 22 个
- **覆盖模块**: runtime, layers, llm, sandbox, tools, router, optimization, zen_rules, unicode
- **缺失覆盖**:
  - `api/server.py` — **无 API 端点测试**
  - `governance/policy.py` GovernanceWorkflow — 无测试
  - `incident_response.py` — 无测试
  - `memory/sqlite_store.py` — 无持久化层集成测试（存在 `test_persistence.py` 但仅覆盖进化归档）
  - `channels/` 适配器 — 无测试
  - `mcp/` 模块 — 无测试
  - `app/server/src/main.py` BFF — 无测试

### TEST-02 建议补充

```
优先级 P0: API 认证测试（先加认证再加测试）
优先级 P1: tools/builtins.py 路径遍历攻防测试
优先级 P1: incident_response.py 事件生命周期测试
优先级 P2: BFF server 集成测试（httpx.AsyncClient + TestClient）
```

---

## 6. 修复优先级清单

| 优先级 | ID | 标题 | 工作量 |
|--------|-----|------|--------|
| **P0** | SEC-01 | API 添加认证 | 2h |
| **P0** | SEC-02 | 轮换泄露的 API Key | 15min |
| **P0** | SEC-03 | 文件工具路径遍历修复 | 1h |
| **P1** | SEC-04 | shell_exec 命令过滤 | 2h |
| **P1** | SEC-05/06 | 命令注入修复 (run_tests, lint, format) | 1h |
| **P1** | ROB-01 | 异常静默吞没添加日志 | 30min |
| **P1** | PERF-04 | EventBus 监听器泄漏修复 | 30min |
| **P2** | SEC-07 | LLM state update 值校验 | 1h |
| **P2** | QUAL-01 | 全局单例重构为依赖注入 | 4h |
| **P2** | QUAL-02 | LLMStateManager 与 LLMManager 统一 | 3h |
| **P2** | ROB-02 | GovernanceWorkflow 配置化 | 1h |
| **P2** | ROB-03 | 枚举值输入校验 | 30min |
| **P2** | ROB-04 | CircuitBreaker 加锁 | 30min |
| **P3** | PERF-01 | RequestCache 改用 OrderedDict | 30min |
| **P3** | PERF-03 | httpx client 复用 | 1h |
| **P3** | ROB-05 | 弃用 API 替换 | 15min |
| **P3** | QUAL-03 | 清理未使用导入 | 5min |

---

## 架构优点

- **分层设计 (L0-L5)** 清晰，关注点分离做得好
- **插件系统** 设计合理，支持依赖解析和生命周期管理
- **审计日志** (JSONL) 线程安全，格式标准
- **事件总线** 解耦了组件通信
- **治理框架** (PolicyEnforcer + ZEN Rules) 方向正确
- **Sandbox** 有 Linux cgroup v2 + unshare 升级路径
- **LLM 多 provider fallback chain** 实用可靠
- **CJK/Unicode 处理** 考虑周全 (NFKC normalize, casefold)
