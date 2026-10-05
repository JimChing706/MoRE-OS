# MoRE OS 可观测性整合总览（收尾）

**日期**: 2026-10-05
**范围**: 把分层测试、治理拦截、Council 复评、Provider 健康四批工作整合为**统一运行健康总览**。
**关联文档**:
[LAYER_TEST_MATRIX](LAYER_TEST_MATRIX_2026-10-05.md) ·
[GOVERNANCE_OBSERVABILITY](GOVERNANCE_OBSERVABILITY_2026-10-05.md) ·
[COUNCIL_REVIEW_BASELINE](COUNCIL_REVIEW_BASELINE_2026-10-05.md) ·
[PROVIDER_HEALTH_OBSERVABILITY](PROVIDER_HEALTH_OBSERVABILITY_2026-10-05.md)

---

## 1. 统一入口

| 入口 | 说明 |
|------|------|
| `GET /api/v1/metrics/overview` | **运行健康总览**：五类指标 + 统一裁决 + 合并告警 |
| `GET /api/v1/metrics/dashboard` | 自托管看板（顶部总览横幅 + 各指标卡片 + 告警横幅） |
| `GET /api/v1/metrics/governance/prometheus` | Prometheus 文本导出（`more_os_*`） |

## 2. 五类核心指标

| 指标族 | 端点 | 关键字段 |
|--------|------|----------|
| LLM 调用 | `/metrics/llm` | `samples`、`success_rate`、`tokens`、`latency_ms{p50,p95}` |
| 交付成功率 | `/delivery/stats` | `total`、`delivered`、`blocked`、`success_rate`、`gate_pass_rate` |
| 治理拦截率 | `/metrics/governance` | `requests`、`blocked_requests`、`blocked_rate`、`by_rule` |
| Council 复评 | `/metrics/council` | `reviews`、`downgrade_rate`、`avg_adjustment`、`by_consensus` |
| Provider 健康 | `/metrics/providers` | `n_unhealthy`、`n_invalid_model`、`n_inference_failed`、`state_model_present` |

## 3. 统一裁决

`overall` = 合并告警（治理 + provider）的最高级别：

| overall | 触发 | 含义 |
|---------|------|------|
| `healthy` | 无告警 | 正常 |
| `degraded` | 有 warning | 降级/需关注（如兜底链降级、治理拦截率偏高） |
| `critical` | 有 critical | 已确证会失败/被绕过（如生效模型缺失、推理探针失败、治理被绕过） |

## 4. 本轮整合新增

* `GET /api/v1/metrics/overview` 聚合端点（五类指标 + `alert_counts` + `overall`）。
* 看板顶部「运行健康总览」横幅（状态 + critical/warning 计数 + 更新时间）。
* `docs/OPERATION_MANUAL.md` 新增 §6.6「可观测性与运行指标」。

## 5. 端到端验证

| 验证 | 结果 |
|------|------|
| 单元/集成测试 | `test_governance_observability.py` 17 · `test_council_review_baseline.py` 19 · `test_provider_health_observability.py` 18 |
| 全量回归 | **1446 passed**（最新一次） |
| 实机端点 | `overview` / `governance` / `council` / `providers` / `prometheus` 均 200 |
| 实机总览裁决 | 修复生效模型后 `overall=healthy`；注入无效生效模型时 `overall=critical` + `state_invalid_model` |

## 6. 累计修复的真实缺陷

| # | 缺陷 | 影响 | 修复 |
|---|------|------|------|
| 1 | L2 DGM / L5 HyperAgent 异常击穿主管道 | 可用性 | 包含式降级 |
| 2 | 治理规则只扫产出、不扫入站请求 | 安全 | `destructive_request_detection` |
| 3 | 谱路由跳过 L3 + ZEN-19 前置拦截未计数 | 指标失真 | 按请求去重 + 护栏入流 |
| 4 | **state manager 生效模型恒为占位符 `local-model`** | **每次 LLM 请求 400，Council 全链失败** | 启动对齐主 provider |
| 5 | `health()` 只探 `/models`，推理失败仍判健康 | 假绿灯 | 可选推理探针 |

*执行人: Codex · 2026-10-05*
