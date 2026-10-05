# MoRE OS 现有代码功能性水平评估

**日期**: 2026-10-05
**方法**: 静态盘点 + 覆盖率实测 + 实机端点探测 + 运行指标采样
**范围**: `more_core/more_core/` 全量代码（~49.6k 行）

---

## 1. 代码资产

| 项 | 数值 |
|----|------|
| Python 代码行 | **49,629** 行 / ~40 个顶层模块 |
| 测试文件 | **95** 个 |
| 测试用例 | **1588**（全绿） |
| Lint | `ruff check` 全通过 |

**规模 Top-6 模块**: core 7,235 · api 5,348 · llm 3,826 · layers 3,424 · codegen 2,834 · security 2,308

---

## 2. 功能面覆盖（实机探测）

### 2.1 API 端点（18/18 全部 200）

| 域 | 端点 | 状态 |
|----|------|:----:|
| 健康 | `/health`、`/monitor/health`、`/monitor/dashboard` | ✅ |
| 指标 | `/metrics/{overview,llm,governance,council,providers,skills,skill-network}` | ✅ |
| 技能 | `/skills`、`/skill-delivery[/stats]` | ✅ |
| 交付 | `/delivery/{stats,ledger}` | ✅ |
| LLM | `/llm/{preflight,state/current,routing}` | ✅ |
| 鉴权 | 无 key 访问 `/skills` | ✅ 401 |

### 2.2 分层架构（L0–L5）

6 层全部注册且可执行；权威链路（谱路由）已核验并被 98 用例门禁覆盖。

### 2.3 技能子系统

5/5 技能 **active**；全部具备 JSON Schema 参数校验；交付台账 **5/5 accepted、完整率 100%**。

### 2.4 治理与可观测

ZEN-19 前置护栏、L3 规则引擎、破坏性请求拦截、五类指标 + 统一裁决 + Prometheus 导出均已验证。

---

## 3. 测试与覆盖率（实测）

| 指标 | 数值 |
|------|------|
| 覆盖率 | **73.8%**（15,375 / 20,845 语句） |
| 测试用例 | 1588 全绿 |

### 3.1 覆盖分布

**优秀（≥95%）**: `layers/l3_symbolic` 100%、`router/task_classifier` 100%、`core/types` 100%、
`codegen/controller` 99%、`v3/dynamic_guardrails` 98.9%、`runtime/bootstrap` 98.4%

**偏低（<35%，≥40 语句）**:

| 模块 | 覆盖率 | 语句 |
|------|:------:|:----:|
| `router/scene_router.py` | **0.0%** | 99 |
| `council/summary_extractor.py` | 7.7% | 52 |
| `llm/providers/openai_compat.py` | 20.5% | 156 |
| `mcp/client.py` | 22.0% | 173 |
| `council/dispute_matrix.py` | 22.5% | 40 |
| `api/routers/requirements.py` | 24.7% | 85 |
| `council/validators.py` | 25.6% | 86 |
| `requirements/parser.py` | 26.4% | 182 |
| `channels/qq_adapter.py` | 27.0% | 122 |
| `channels/telegram_adapter.py` | 28.2% | 71 |
| `sandbox/linux_sandbox.py` | 28.4% | 81 |
| `plugins/manager.py` | 30.2% | 96 |
| `llm/providers/ollama.py` | 30.5% | 59 |

**按模块聚合**: requirements 27.2% · channels 41.3% · router 45.7% · cli 46.8% ·
mcp 52.2% · plugins 52.8% · council 55.7% · tools 55.9% · metacognition 59.4% ·
api 62.0% · llm 65.8% · runtime 77.4%

---

## 4. 运行指标（实机 24h 采样）

| 指标 | 数值 | 解读 |
|------|------|------|
| 交付总数 | 66 | delivered 34 / blocked 15 / failed 17 |
| **交付成功率** | **51.5%** | 含早期故障期样本 |
| 闸门通过率 | 100% | 拦截均来自控制器裁决，非闸门 |
| 技能执行 | 9 次 / 成功率 55.6% | 含早期失败样本 |
| 技能注册 | 5/5 active | 健康 |
| Provider 健康 | 2 个 / 无效模型 0 | 健康 |
| LLM 近 1h | samples=0 | 无流量 |

---

## 5. 评分卡

| 维度 | 评分 | 依据 |
|------|:----:|------|
| **功能完备性** | 8.0 / 10 | 6 层 + 5 技能 + 交付/治理/可观测齐备；18/18 端点通 |
| **正确性** | 6.5 / 10 | 交付 51.5% / 技能 55.6%（含历史故障）；核心链路修复后显著改善 |
| **测试充分性** | 7.5 / 10 | 1588 用例 / 73.8% 覆盖；但 13 个较大模块 <35% |
| **可观测性** | 8.5 / 10 | 七类遥测表 + 统一裁决 + Prometheus + 看板 |
| **安全性** | 8.0 / 10 | SSRF 防护 / 代码沙箱 / RBAC / ZEN-19 / 参数 Schema；沙箱非强隔离 |
| **健壮性** | 7.5 / 10 | 多处故障隔离（L2/L5/技能/链）；存在"快照过期误报" |
| **可维护性** | 7.0 / 10 | ruff 全通过、文档齐全；但存死代码与双路由历史包袱 |
| **综合** | **7.6 / 10** | 工程化程度高，功能完整，正确性/覆盖仍有提升空间 |

---

## 6. 本次评估新发现

| # | 发现 | 维度 | 影响 |
|---|------|------|------|
| ~~A-1~~ | ~~时间点快照 + 滑窗查询 → 误报~~ | 可观测性 | **已修复（2026-10-05）**：查询改为"取最新快照（不限窗口）"+ 新鲜度（`age_s`/`stale`）；过期时改用 **info 级 `*_stale`**，不再影响 `overall` 裁决。见 §9 |
| **A-2** | `router/scene_router.py` **0% 覆盖**：仅被 `LayerRouter.route_with_scene()` 使用，而该方法**无任何调用方** → **死代码 ~160 行** | 可维护性 | 低-中 |
| ~~A-3~~ | ~~成功率缺近期窗口（历史样本污染）~~ | 正确性 | **已修复（2026-10-05）**：交付/技能均新增"近 1h / 24h"双窗口 + 趋势；`no_data` 区分"无样本"与"下降"。见 §9 |

---

## 7. 优化建议（按优先级）

| 优先级 | 建议 | 对应发现 |
|:------:|------|----------|
| **P0** | 快照类指标改为"取最新快照（不限窗口）+ 标注新鲜度"，或延长窗口并在过期时给出**独立**的 `*_stale` 提示而非 `missing` | A-1 |
| **P1** | 为低覆盖核心模块补测试：`requirements/parser`、`council/validators`、`plugins/manager`、`llm/providers/ollama` | 覆盖率 |
| ~~P1~~ | ~~交付/技能成功率增加"近 1h / 24h"双窗口与趋势~~ ✅ **已执行（见 §9）** | A-3 |
| **P2** | 清理 `scene_router` 死代码，或为 `route_with_scene` 接入真实调用点并补测试 | A-2 |
| **P2** | `openai_compat` / `channels/*` 等外部依赖模块补契约测试或显式标注"未覆盖" | 覆盖率 |
| **P3** | 建立端到端性能基准（当前仅单点测量，无回归基线） | 正确性 |

---

## 8. P0（A-1）修复详情

**问题**：`query_provider_health` / `query_skill_network_health` 按滑窗（`ts >= now - window_s`）取快照；
预检快照滑出窗口后返回**空**，被判定为 `*_preflight_missing`（warning）→ 系统健康却显示 **degraded**。

**修复**：

| 项 | 修复前 | 修复后 |
|----|--------|--------|
| 取数 | 按窗口过滤，窗口外=空 | **取最新快照（不限窗口）** |
| 新鲜度 | 无 | 返回 `age_s` / `stale`，并保留窗口内计数 `snapshots` |
| 过期语义 | 当作 `missing`（warning） | **`*_preflight_stale`（info）**，不参与 overall 裁决 |
| 真正无快照 | `missing`（warning） | 不变（仍是 warning） |
| 看板 | 仅 critical/warning 样式 | 新增 `info` 中性样式 |

**实测**：

| 场景 | 修复前 overall | 修复后 overall |
|------|:-------------:|:-------------:|
| `window_s=3600`（快照 1h 前） | degraded | **healthy** |
| `window_s=60`（快照 >60s） | degraded | **healthy** |
| 快照 2h 前（手工构造） | — | healthy + `*_preflight_stale`(**info**) |
| 完全无快照 | degraded | degraded（`missing` warning，语义正确） |

> 语义澄清：**"过期" ≠ "缺失"** —— 前者是数据新鲜度（info），后者才是观测缺口（warning）。

---

## 9. P1（A-3）修复详情：成功率双窗口 + 趋势

**问题**：`delivery.stats()` / `query_skill_stats()` 仅单窗口，历史故障期样本混入当前判断
（如交付 24h 51.5% 掩盖了修复后的 1h 100%）。

**修复**：

| 项 | 实现 |
|----|------|
| 多窗口 | `DeliveryLedger.stats_windows()` / `query_skill_stats_windows()` → `{"windows": {"1h":…,"24h":…}, "trend": …}` |
| 趋势 | `success_trend(recent, baseline, recent_samples=…)` → `improving`/`declining`/`stable`/**`no_data`** |
| 语义加固 | **`recent_samples == 0` → `no_data`**：无样本 ≠ 下降（避免二次误报，与 A-1 同类） |
| 接口 | `/delivery/stats`、`/metrics/skills` 增加 `windows`；`/metrics/overview` 增加 `recent` 块 |
| 看板 | 交付/技能卡片显示"近1h · 24h · 趋势" |

**实测**：

```
delivery: 1h = 100%   24h = 61.8%   trend = improving    ← 当前状态与累积区分开
skills  : 1h = 0 runs 24h = 55.6%   trend = no_data      ← 无样本不再误报 declining
```

---

## 10. 结论

MoRE OS 现有代码**功能覆盖完整、工程化程度高**（49.6k 行 / 1588 测试 / 73.8% 覆盖 /
ruff 全通过 / 18 端点全通 / 多层可观测 + 治理 + 安全防护），综合 **7.6/10**。

主要短板集中在**正确性的量化**（交付成功率含历史样本、缺趋势）与
**覆盖率长尾**（13 个较大模块 <35%），另有 1 处**可观测误报**（A-1）应优先修复。

*执行人: Codex · 2026-10-05*
