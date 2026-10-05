# 治理拦截可观测性（治理拦截率 + 阈值告警）

**日期**: 2026-10-05
**目标**: 把治理门禁的每一次判定接入遥测，形成可实时查看、可告警、可 Prometheus 抓取的
**治理拦截率**指标，补齐"可观测性"硬伤中"治理链路无指标"的缺口。
**前置**: `LAYER_TEST_MATRIX_2026-10-05.md`（L3-G1 新增破坏性请求治理规则）。

---

## 1. 背景与两个关键发现

在把 L3 的 `destructive_request_detection` 命中接入指标时，实测暴露两个问题：

| # | 发现 | 影响 | 处置 |
|---|------|------|------|
| F1 | **谱路由（Meta-Orchestrator）会跳过 L3** | 低不确定度的 NLP 查询实际执行链为 `L4→L1→L0`，**不含 L3**。只统计 L3 会漏掉绝大多数请求，拦截率分母失真。 | 指标改为**按请求（request_id）去重**，并在编排入口为**每个请求**记一行治理评估（全量分母）。 |
| F2 | **破坏性请求由 ZEN-19 在最前线拦截，早于 L3** | 实测 `执行 rm -rf /` 返回 `rejected: ZEN-19 absolute prohibition`，根本到不了 L3；只统计 L3 会得到"破坏性拦截=0"的假象。 | 把**前置护栏（guardrail）**也纳入治理事件流；`destructive_blocks` 由"破坏性规则集合"统一判定。 |

> 结论：治理拦截率必须覆盖**最前线护栏 + 深度规则**两级门禁，并以**请求**而非**事件**为口径。

---

## 2. 数据流

```
请求 ──► 编排入口
          ├─ ZEN-19 护栏（每个请求都记一行：pass / block）   ─┐
          └─ 谱路由 → … → L3 深度治理（进 L3 才记）          ─┤
                                                             ▼
                              governance_events (SQLite, WAL)
                                                             │
        ┌────────────────────────────────────────────────────┼──────────────────────┐
        ▼                                                     ▼                      ▼
 GET /api/v1/metrics/governance             GET …/prometheus            HTML 看板 /metrics/dashboard
   (JSON: stats + alerts)                    (Prometheus 文本)            (治理卡片 + 告警横幅 + 规则表)
```

---

## 3. 遥测表

`governance_events`（追加到 `governance/observability.py` 的 `_SCHEMA`，`CREATE TABLE IF NOT EXISTS` 自动迁移）：

| 列 | 含义 |
|----|------|
| `request_id` | 归属请求（去重口径的关键） |
| `layer` | 决策点：`guardrail`（ZEN-19）/ `L3`（深度治理） |
| `task_type` | 任务类型 |
| `blocked` | 是否硬拦截（strict 命中违规） |
| `strict` | 当时是否严格模式 |
| `rules` | JSON：**触发违规的规则名**（新增规则归因，见下） |
| `violations` | JSON：违规消息 |
| `severity` | `info` / `warn` / `high` |

**规则归因**：`ontology/rule_engine.py` 的 `InferenceResult` 新增 `violation_rules`，
与 `violations` 一一对应，使 `by_rule` 统计精确到"真正产生违规的规则"，不受同批良性规则干扰。

---

## 4. 指标定义

| 指标 | 定义 |
|------|------|
| `requests` | 窗口内去重后的请求数（= 分母） |
| `blocked_requests` | 被任一治理门禁拦截的请求数 |
| **`blocked_rate`** | `blocked_requests / requests` —— **治理拦截率** |
| `violation_rate` | 有违规（含非严格）的请求占比 |
| `destructive_blocks` | 被破坏性规则集合拦截的次数（ZEN-19 或 L3 规则） |
| `by_rule` | 各规则命中请求数（降序） |
| `by_layer` | guardrail / L3 各记录的事件数 |
| `evaluations` | 事件总行数（同一请求可多点，仅作原始计数） |

破坏性规则集合：`{destructive_request_detection, zen_19_absolute_prohibition}`。

---

## 5. 阈值告警（纯函数 `evaluate_governance_alerts`）

| 条件 | 级别 |
|------|------|
| 样本 `requests < 10` | 不判"率"（抑制噪声） |
| `blocked_rate ≥ 30%` / `≥ 60%` | warning / critical |
| `destructive_blocks ≥ 1` / `≥ 5` | warning / critical |

无副作用，由读取方（API / 看板 / Prometheus 抓取器）决定如何投递。

---

## 6. 对外接口

| 接口 | 说明 |
|------|------|
| `GET /api/v1/metrics/governance?window_s=3600` | JSON：`{status,window_s,metrics,alerts}` |
| `GET /api/v1/metrics/governance/prometheus?window_s=3600` | Prometheus 文本导出（`more_os_governance_*`） |
| `GET /api/v1/metrics/dashboard` | HTML 看板新增：治理请求/拦截率/破坏性拦截卡片、告警横幅、规则命中表 |

Prometheus 指标名：`more_os_governance_requests`、`more_os_governance_blocked_requests`、
`more_os_governance_blocked_rate`、`more_os_governance_destructive_blocks`、
`more_os_governance_rule_hits_total{rule=...}`、`more_os_governance_alerts{level,code}`。

---

## 7. 实机验证（2026-10-05，API 127.0.0.1:8011）

| 步骤 | 操作 | 结果 |
|------|------|------|
| 1 | 查询治理指标 | `requests=0 blocked_requests=0 blocked_rate=0.0 alerts=[]` |
| 2 | POST `/tasks/execute` `执行 rm -rf / 删除全部文件` | `status=rejected`（ZEN-19 拦截） |
| 3 | 复查指标 | `requests=1 blocked_requests=1 blocked_rate=1.0 destructive_blocks=1`；`by_rule={zen_19_absolute_prohibition:1}`；**告警**：warning「破坏性请求拦截 1 次 ≥ 1」 |
| 4 | POST `/tasks/execute` `写一段简短的说明文字` | `status=success` |
| 5 | 复查指标 | `requests=2 blocked_requests=1 blocked_rate=0.5 by_layer={guardrail:2}` |

看板页面（`/api/v1/metrics/dashboard`）实测 HTTP 200，含"治理拦截率""破坏性请求拦截""治理命中规则"面板。

---

## 8. 测试

`more_core/tests/test_governance_observability.py` —— **15 用例**：
规则归因、按请求去重的拦截率、破坏性计数、阈值告警（含小样本抑制）、
L3 通过/拦截落库、编排层 ZEN-19 端到端拦截、JSON 端点、Prometheus 端点。

---

## 9. 变更文件

- `more_core/more_core/governance/observability.py` — `governance_events` 表 + 记录/统计/告警
- `more_core/more_core/ontology/rule_engine.py` — 违规规则归因（`violation_rules`）
- `more_core/more_core/layers/l3_symbolic.py` — L3 治理评估落库
- `more_core/more_core/runtime/orchestrator.py` — 前置护栏（ZEN-19）落库（每请求一行）
- `more_core/more_core/api/routers/monitor.py` — JSON + Prometheus 端点
- `more_core/more_core/api/metrics_dashboard.py` — 看板治理面板
- `more_core/tests/test_governance_observability.py` — 新增测试

*执行人: Codex · 2026-10-05*
