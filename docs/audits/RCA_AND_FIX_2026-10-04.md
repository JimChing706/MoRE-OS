# MoRE OS 三大核心硬伤 — 根因分析、修复落地与上线验证

**报告日期**: 2026-10-04
**修复范围**: 产出正确性 · 交付可信度 · 可观测性
**验证结论**: ✅ 三项硬伤均已修复并完成上线验证（21/21 端到端检查通过 + 1172 单测全绿）

---

## 0. 总览

| # | 硬伤 | 触发节点 | 底层成因（一句话） | 状态 |
|:-:|------|----------|--------------------|:----:|
| 1 | 产出正确性 | 交付前的输出过滤 + 缺失校验闸门 | 脱敏正则匹配 Python 关键字参数，把 `key=lambda` 改写成 `[ENV_SECRET_REDACTED]`；且没有语法/逻辑/需求闸门拦截 | ✅ 已修 |
| 2 | 交付可信度 | `orchestrator.execute()` 返回前 | 交付物无台账、无版本、无权责、无哈希；成功率无量化模型 | ✅ 已修 |
| 3 | 可观测性 | `LLMManager` 各入口 + 遥测单例 | 存储模块导入路径错误 + **只有 `generate()` 被插桩**（`generate_with_fallback_chain` 等 3 个入口无采集） | ✅ 已修 |

**最突出矛盾的定位**：系统自报 `tokens_used` 有值，但遥测表始终为 0。原因是
①`observability.py` 的 `from .config import Settings` 指向不存在的模块导致整条遥测静默失效；
②修复①之后仍为 0，进一步定位到 L0 实际走的是 `generate_with_fallback_chain()`，
而 `record_llm_call` 只写在 `generate()` 内 —— **指标在链路的真实路径上根本没有埋点**。

---

## 1. 硬伤一：产出正确性

### 1.1 根因分析（结构化）

| 维度 | 内容 |
|------|------|
| **触发节点** | `runtime/orchestrator.py:555` `filtered_output = self.output_filter.filter(str(output))` |
| **规则位置** | `security/output_filter.py` 规则 `env_secret` |
| **原始规则** | `re.compile(r"(?:PASSWORD|SECRET|TOKEN|KEY)\s*=\s*\S+", re.IGNORECASE)` |
| **触发条件** | 生成代码中出现任何 `key=` / `token=` / `secret=` / `password=` 形参或赋值 |
| **失败链** | L0 沙箱验证**原始**代码 → 通过（`sandbox: true`, verdict `pass`）→ 返回前 filter 改写 → 交付**被破坏**的代码 → 仍报 `status=success` |
| **二次缺陷** | 无任何语法/逻辑/需求校验闸门，破坏后的工件可直接放行 |
| **量化影响** | 把该规则作用于 MoRE 自身源码：**135 行 / 49 个文件**被改写（占 0.31%）；基准中 `merge_intervals` 任务 100% 交付不可编译代码 |
| **性质** | **验证对象 ≠ 交付对象**（TOCTOU 式缺陷），属"假成功" |

最小复现（修复前）：

```
平台自报 : status=success   verdict=pass   sandbox_ok=True
交付代码 : py_compile rc=1
破坏行   : sorted_intervals = sorted(intervals, [ENV_SECRET_REDACTED] x: x[0])
```

### 1.2 修复落地

| # | 变更 | 文件 |
|:-:|------|------|
| 1 | 脱敏规则重写：仅匹配 ①强关键词+引号≥12 字面量 ②`.env` 风格超长无引号值；**移除裸 `KEY`** | `security/output_filter.py` |
| 2 | 新增多维闸门模块：`syntax_gate` / `logic_gate` / `requirement_gate` / `run_gates` | `codegen/gates.py`（新） |
| 3 | 交付前跑闸门；**过滤前 vs 过滤后语法对比**，若过滤破坏了原本合法的代码则回退到过滤前工件并记审计事件 | `runtime/orchestrator.py` |
| 4 | 闸门 blocking 失败 → 任务降级为 `FAILED` + 记 `delivery_blocked` 审计 + **不写入结果缓存** | `runtime/orchestrator.py` |
| 5 | 模板/原生通路同样接入 `run_gates(require_logic=True)`，拦截 placeholder 空壳交付 | `api/routers/tasks.py` |

校验维度说明：

* **语法**：Python 用 `compile()` 真实解析；Rust/TS/JS 等用括号/引号配平 + 未闭合检测（blocking）。
* **逻辑**：识别 `pass` 空函数体、`NotImplementedError`、`TODO/FIXME`、`placeholder`、`unimplemented!()`
  —— 短小且全为占位时 **blocking**（正是 cs_shooter 空壳工程的特征）。
* **需求匹配**：从任务描述抽取必须出现的标识符（反引号符号 / `def|class|fn` 名 / 调用式名称），
  计算覆盖率，低于 60% 即 blocking。

### 1.3 验证

| 检查 | 结果 |
|------|------|
| 交付代码不再含 `[ENV_SECRET_REDACTED]` | ✅ |
| 交付代码 `py_compile` 通过 | ✅ |
| 返回体携带 `metadata.delivery_gates` | ✅ |
| 闸门含 syntax / logic / requirement 三类 | ✅ |
| 过滤器回归：`key=lambda` / `def f(key=1, token=None)` / `redis.set(key=...)` 不被改写 | ✅（5 例参数化） |
| 过滤器仍能脱敏真密钥（引号字面量 / 长无引号值） | ✅（3 例参数化） |
| placeholder 工程被 logic 闸门拦截 | ✅ |

---

## 2. 硬伤二：交付可信度

### 2.1 根因分析（结构化）

| 维度 | 内容 |
|------|------|
| **触发节点** | `orchestrator.execute()` 构造 `TaskResult` 后直接返回；原生通路 `_execute_task_background_v2` 写 task_store 后结束 |
| **缺失能力** | ① 无交付台账 ② 无版本管理（同一 task 多次交付不可区分）③ 无权责标记 ④ 无工件哈希 ⑤ 无成功率量化 |
| **可观测后果** | 无法回答"这个产物是谁在什么时候、用哪个模型、经过哪些校验交付的" |
| **叠加风险** | 未验证的产物会进入结果缓存，被后续相同 query 复用（坏结果扩散） |
| **性质** | 治理与审计能力缺失（"流程走完"≠"交付可信"） |

### 2.2 修复落地

| # | 变更 | 文件 |
|:-:|------|------|
| 1 | 新增交付台账（SQLite，append-only）：`delivery_id / task_id / version / status / reason / artifact_sha256 / verdict / gates / actor / provider / model / trace_id` | `codegen/delivery_ledger.py`（新） |
| 2 | 版本管理：同一 `task_id` 的交付 `version` 自增，可回溯全部历史 | 同上 |
| 3 | 成功率量化模型 `stats()`：总量/已交付/已拦截/失败 + 闸门通过率 + 按任务类型切分 | 同上 |
| 4 | 两条通路（LLM 通路 + 模板通路）均写入台账 | `runtime/orchestrator.py`、`api/routers/tasks.py` |
| 5 | 对外接口：`/delivery/stats`、`/delivery/ledger`、`/delivery/{task_id}` | `api/routers/delivery.py`（新） |
| 6 | 被闸门拦截的产物**不进入结果缓存** | `runtime/orchestrator.py` |

状态语义：`delivered`（已交付）/ `blocked`（闸门拦截，产物不可信）/ `failed`（执行失败）。

### 2.3 验证

| 检查 | 结果 |
|------|------|
| 台账端点可用并写入记录 | ✅（5 条） |
| 记录含 64 位工件哈希 | ✅ `c3dfa3db54ae…` |
| 记录含权责主体 `actor` | ✅ `verify-fixes` |
| 记录含闸门结论与 `gates_passed` | ✅ |
| 版本号自增（同 task 多次交付） | ✅ `v1 → v2`（单测） |
| 按任务追溯交付历史 | ✅ `/delivery/{task_id}` 返回 versions |
| 交付成功率模型 | ✅ `total/delivered/blocked/failed/success_rate/gate_pass_rate/by_task_type` |

---

## 3. 硬伤三：可观测性（本次最高优先级）

### 3.1 根因分析（结构化）

**根因 A — 存储层导入错误（彻底静默）**

| 维度 | 内容 |
|------|------|
| 位置 | `governance/observability.py:162` |
| 代码 | `from .config import Settings as _S` → 解析为 `more_core.governance.config`（**不存在**） |
| 正确路径 | `from ..core.config import Settings` |
| 放大因素 | 模块设计为 "Silently no-ops on any failure"，异常被 `except Exception: pass` 吞掉 |
| 实测后果 | 无 `logs/observability.sqlite`；`/health` 的 `recent_llm_success_rate` 恒为 `0.0`；`injection_counts_1h` 恒为空 |

**根因 B — 埋点只覆盖 1/4 入口（修复 A 后仍为 0）**

| 入口 | 是否有 `record_llm_call` |
|------|:----------------------:|
| `LLMManager.generate()` | ✅ 有 |
| `LLMManager.generate_with_fallback_chain()` | ❌ **无**（L0 实际走这条） |
| `LLMManager.generate_parallel()` | ❌ 无 |
| `LLMManager.stream()` | ❌ 无 |

L0 `_do_generate()` 在 tiered chain > 1 时调用 `generate_with_fallback_chain()`，
因此**生产路径上的 token/延迟一条都没采到**，而平台自报 `tokens_used` 却有值——
两者长期不一致，正是"核心运行指标缺失"的直接原因。

### 3.2 修复落地

| # | 变更 | 文件 |
|:-:|------|------|
| 1 | 修正导入路径 → 遥测库可正常创建与写入 | `governance/observability.py` |
| 2 | 新增 `summary(window_s)`：调用量 / 成功率 / prompt+completion token / 延迟 avg·p50·p95·max / 按 provider 分解；并显式区分"无数据"与"遥测损坏"（`error` 字段） | 同上 |
| 3 | 新增统一出口 `LLMManager._emit_llm_call()`（best-effort，绝不打断主链路） | `llm/manager.py` |
| 4 | **四个入口全部插桩**：`generate` / `generate_with_fallback_chain` / `generate_parallel` / `stream`（含 cache 命中、重试 attempt、失败原因） | `llm/manager.py` |
| 5 | 对外接口：`/metrics/llm`（聚合）、`/metrics/llm/recent`（明细） | `api/routers/monitor.py` |
| 6 | `/health` 暴露 `tokens_1h` 与 `latency_ms_1h` | `api/routers/health.py` |
| 7 | **实时可视化看板** `/metrics/dashboard`（自托管单文件 HTML，无 CDN、无密钥内嵌） | `api/metrics_dashboard.py`（新） |
| 8 | 测试隔离：每个用例独立遥测库 + 独立台账库，避免污染真实数据 | `tests/conftest.py` |

### 3.3 验证（真实任务流量）

```
执行前 samples: 3   tokens: 45
任务: task_62c042fa760e  success  平台自报 tokens: 5663
执行后 samples: 5   tokens: 5708
新增样本: 2   新增 token: 5663      ← 与平台自报完全一致
最近调用: provider=lmstudio  model=ornith-ai/ornith-1.5-9b  prompt_tokens=5559
          request_id=chain_1791085208096411  attempt=1
```

| 检查 | 结果 |
|------|------|
| 指标端点可用 | ✅ |
| 真实任务产生遥测样本 | ✅ `samples=7` |
| token 消耗已记录且与自报一致 | ✅ `17,618` |
| 延迟 p50/p95/max 已记录 | ✅ `123.4 / 17575.1 / 17575.1 ms` |
| 成功率已计算 | ✅ `0.714` |
| 最近调用明细可查 | ✅ |
| health 暴露 tokens/latency | ✅ |
| 可视化看板可访问 | ✅ `HTTP 200`, 5827 bytes |

---

## 4. 上线验证汇总

| 验证项 | 结果 |
|--------|------|
| 三大硬伤端到端检查 | **21 / 21 PASS** |
| 后端全量回归 | **1172 passed / 0 failed** |
| 新增回归测试 | 25 项（闸门 8 + 过滤器 8 + 遥测 4 + 台账 5） |
| 新增文件静态检查 | ruff clean / mypy clean |
| 指标看板 | `GET /api/v1/metrics/dashboard` → 200 |

### 修复前后对比

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 交付物可编译率（基准） | 1/4 | 交付前强制语法闸门 |
| 遥测入库行数（真实任务） | **0** | 2 行/任务（与自报 token 一致） |
| 遥测库文件 | 不存在 | `logs/observability.sqlite` |
| health token 指标 | 无 | `tokens_1h` + `latency_ms_1h` |
| 交付台账 | 无 | 有（哈希/版本/权责/闸门） |
| 交付成功率模型 | 无 | 有（含按任务类型） |
| 拦截机制 | 无 | 闸门 blocking → `FAILED` + `delivery_blocked` 审计 + 不入缓存 |

---

## 5. 残留风险与后续建议

1. **路由误判（未修）**：`TaskTemplateSelector.CS_RE` 的裸 `cs`/`fps` 仍会把
   `docs/metrics/statistics/specs` 误判为 cs_shooter 任务，建议改为词边界匹配并优先使用 ITD frontmatter。
2. **可观测性覆盖面**：本次已覆盖 LLM 四入口；L3/L4/L5 层内部耗时与非 LLM 阶段耗时尚未分段计时，
   建议补 stage 级 span 以支撑端到端延迟归因。
3. **护栏**：新增的 `logic_gate` 目前用静态启发式识别占位实现，对"看起来完整但逻辑错误"的代码无效，
   建议后续接入"断言必须通过"（`assertions_required`）作为默认策略。
4. **前端看板**：现有 React `Home.tsx` 未接入真实遥测（且其 fetch 未带 API Key，启用鉴权后会 401），
   建议后续把 `/metrics/llm` 接入前端并统一注入认证头。

---

*修复人: Codex · 2026-10-04 · 全链路根因分析 + 代码落地 + 上线验证*
