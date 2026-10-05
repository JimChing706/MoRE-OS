# L4→L5 Council 复评量化基线 + 看板接入

**日期**: 2026-10-05
**目标**: 为 L4→L5 的 Council 复评建立**可回归的数值契约**（高风险 + 分歧 → 置信度下修），
并把复评结果纳入同一治理看板（L5 元认知的可观测闭环）。
**前置**: `GOVERNANCE_OBSERVABILITY_2026-10-05.md`（治理遥测与看板）。

---

## 1. 背景

L4 认知层在困难任务上调用 Council 多视角评审，把 `CouncilResult` 写入
`scratch["plan"]["council_result"]`；L5 元认知层用 `_review_council_output` 交叉核对
"校准置信度"与"Council 风险"，在**分歧/高风险**时下修 alignment（`result.confidence`）。

此前该下修逻辑**只有一处临时断言**，缺少数值契约与统一看板，属于"产出正确性/可观测性"盲区。

---

## 2. 下修公式（数值契约）

```
adjustment = 0
分歧 consensus == "divided":              -0.15
弱共识 consensus == "weak":               -0.08
高风险 severity == "high":                -0.05 × min(n_high, 3)
乐观放大风险:  risk_count ≥ 3 且 alignment > 0.85 → -0.05
council 错误:                             -0.05 × min(n_errors, 3)
下限 clamp:                               max(adjustment, -0.5)
```

> 说明：各项叠加的最大幅值恰为 `0.15 + 0.15 + 0.05 + 0.15 = 0.50`，即下限 `-0.5` 是边界保护。

---

## 3. 量化基线用例（`test_council_review_baseline.py`）

| consensus | 风险 | 错误 | alignment | 期望下修 |
|-----------|------|------|-----------|:--------:|
| strong | — | — | 0.80 | `0.0` |
| moderate | — | — | 0.80 | `0.0` |
| weak | — | — | 0.80 | `-0.08` |
| **divided** | — | — | 0.80 | `-0.15` |
| strong | 1 high | — | 0.80 | `-0.05` |
| strong | 3 high | — | 0.80 | `-0.15` |
| strong | 5 high | — | 0.80 | `-0.15`（封顶 3） |
| **divided** | 2 high | — | 0.80 | `-0.25` |
| **divided** | 3 high | — | 0.90 | `-0.35`（含乐观放大） |
| strong | — | 3 | 0.80 | `-0.15`（封顶 3） |
| **divided** | 3 high + 1 med | 3 | 0.90 | `-0.50`（触达下限） |

另含两条结构用例：风险列表截断到 5 但 `risk_count`/`high_risk_count` 保持完整；无风险无误时中性。

**实测**：19 用例全部通过，公式与上表逐一吻合。

---

## 4. 遥测接入

新增 `council_reviews` 表（`governance/observability.py`，`CREATE TABLE IF NOT EXISTS` 自动迁移）：

| 列 | 含义 |
|----|------|
| `request_id` | 归属请求 |
| `consensus` | strong / moderate / weak / divided |
| `risk_count` / `high_risks` / `errors` | 完整计数（非截断值） |
| `alignment_before` / `adjustment` / `alignment_after` | 下修前后与调整量 |
| `downgraded` | adjustment < 0 |

L5 `process` 在完成复评后调用 `_record_council_review`（异常吞没，遥测不得影响主链路）。
`_review_council_output` 返回值新增 `risk_count` / `high_risk_count`（因 `risks` 被截断到 5）。

### 聚合指标 `query_council_stats`

`reviews` / `downgraded` / **`downgrade_rate`** / `divided` / `weak` /
`high_risk_reviews` / `avg_adjustment` / `min_adjustment` / `by_consensus`。

---

## 5. 对外接口

| 接口 | 说明 |
|------|------|
| `GET /api/v1/metrics/council?window_s=3600` | JSON：Council 复评指标 |
| `GET /api/v1/metrics/governance/prometheus` | 追加 `more_os_council_*` 指标 |
| `GET /api/v1/metrics/dashboard` | 看板新增：Council 复评数、下修率、平均下修卡片 |

Prometheus 追加：`more_os_council_reviews`、`more_os_council_downgrade_rate`、
`more_os_council_avg_adjustment`、`more_os_council_reviews_by_consensus{consensus=...}`。

---

## 6. 测试与回归

- `more_core/tests/test_council_review_baseline.py` —— **19 用例**（量化矩阵 + 结构 + 集成 + 遥测聚合 + 接口）。
- 相关子集（L5/L4/治理/L0-L5 矩阵/交付指标）：**177 passed**。

---

## 7. 实机验证与限制（2026-10-05）

* **端点实测**：`GET /api/v1/metrics/council` → HTTP 200 零值形态；
  `GET /api/v1/metrics/governance/prometheus` → 含 `more_os_council_*` 指标行。
* **真实 Council 触发（受限）**：提交高难度 `architecture_design` 任务，
  因本地 LM Studio provider 配置的模型标识 `local-model` 未下载
  （`Invalid model identifier "local-model"`），Council 5 个角色全部失败 →
  任务 `failed`、无 `council_result`、`reviews=0`。
  **判定：环境配置问题，非代码缺陷**。
* 因此"下修→落库"路径以**确定性集成测试**为准（`test_l5_applies_downgrade_and_records_telemetry`，
  用真实 L5 层 + 构造 CouncilResult）；待本地模型修复后可复跑实机 Council。

---

## 8. 变更文件

- `more_core/more_core/governance/observability.py` — `council_reviews` 表 + `record_council_review` / `query_council_stats`
- `more_core/more_core/layers/l5_metacognition.py` — 复评落库 + 完整风险计数
- `more_core/more_core/api/routers/monitor.py` — `/metrics/council` + Prometheus 追加
- `more_core/more_core/api/metrics_dashboard.py` — Council 看板卡片
- `more_core/tests/test_council_review_baseline.py` — 新增测试

*执行人: Codex · 2026-10-05*
