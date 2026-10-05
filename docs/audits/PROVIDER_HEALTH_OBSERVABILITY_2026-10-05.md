# LLM Provider 健康预检可观测性（无效模型标识 / 配置漂移告警）

**日期**: 2026-10-05
**目标**: 把 `preflight_llm` 的健康预检结果**落库、上同一看板、触发阈值告警**，
让"模型名写错 / 配置漂移 / provider 不健康 / 兜底链断掉"这类**静默故障**在运行期可见。
**前置**: `GOVERNANCE_OBSERVABILITY_2026-10-05.md`、`COUNCIL_REVIEW_BASELINE_2026-10-05.md`。

---

## 1. 背景（真实事故）

`more_core/.env` 里 `MORE_LMSTUDIO_MODEL=ornith-1.5-35b-a3b`（正确），
但高难度任务实际请求发出的是 `local-model`，LM Studio 返回：

```
HTTP 400: Invalid model identifier "local-model".
```

后果：Council 5 个角色全部失败、高难度任务整链失败——**此前无任何告警**。

### 1.1 关键发现：配置漂移导致的"假绿灯"

| 位置 | model 值 | 说明 |
|------|----------|------|
| provider 配置（预检原本只查这里） | `ornith-1.5-35b-a3b` | 存在（41 个模型中）→ **预检说 OK** |
| **state manager 生效模型**（实际请求发送的） | `local-model` | 不存在 → **每次请求失败** |

根因：`llm/state_manager.py` 的 `LLMCallState.model` 默认值是占位符 `"local-model"`，
而每次请求以 state manager 的 model 为准。**只检查 provider 自身配置会给出假绿灯**。

修复：预检**同时校验生效模型**（`state_provider` / `state_model` / `state_model_present`），
发现漂移即 critical 告警。

---

## 2. 遥测表

`provider_health_snapshots`（追加到 `governance/observability.py` 的 `_SCHEMA`，自动迁移）：

| 列 | 含义 |
|----|------|
| `ok` | 预检是否无告警 |
| `degraded` | 兜底链已注册 provider < 2 |
| `n_providers` | provider 数 |
| `n_unhealthy` | 健康检查失败数 |
| `n_invalid_model` | **模型缺失数（provider 配置 + 生效模型）** |
| `report` | 完整 `LLMPreflight.to_dict()` JSON（含 provider 明细与 state 字段） |

### 公共 API

- `record_provider_health(report)` —— 落库一次快照（never raises）
- `query_provider_health(window_s)` —— 返回**最新快照** + `snapshots` 计数
- `evaluate_provider_alerts(health)` —— 纯函数阈值告警

---

## 3. 阈值告警

| 条件 | 级别 | code |
|------|:----:|------|
| **生效模型（state manager）缺失**（配置漂移） | critical | `state_invalid_model` |
| provider 配置模型缺失 | critical | `provider_invalid_model` |
| provider 健康检查失败 | critical | `provider_unhealthy` |
| 无任何 provider 注册 | critical | `no_provider_registered` |
| 兜底链降级（< 2 已注册） | warning | `fallback_chain_degraded` |
| 无任何预检快照 | warning | `provider_preflight_missing` |

---

## 4. 采集时机

| 时机 | 位置 |
|------|------|
| 启动预检 | `MoRECore.start()` → `record_provider_health(self.llm_preflight)` |
| 按需复检 | `GET /api/v1/llm/preflight`（默认写库，`record=0` 关闭） |

---

## 5. 对外接口

| 接口 | 说明 |
|------|------|
| `GET /api/v1/metrics/providers?window_s=3600` | JSON：`{health, alerts}` |
| `GET /api/v1/llm/preflight?record=1` | 复检并刷新快照 |
| `GET /api/v1/metrics/governance/prometheus` | 追加 `more_os_provider_*` |
| `GET /api/v1/metrics/dashboard` | 「Provider 健康」卡片 + provider 告警并入横幅 |

Prometheus 追加：`more_os_provider_preflight_ok`、`more_os_provider_unhealthy`、
`more_os_provider_invalid_model`、`more_os_provider_healthy{provider}`、
`more_os_provider_model_present{provider}`、`more_os_provider_alerts{level,code}`。

---

## 6. 实机验证（2026-10-05，127.0.0.1:8011）

本机**正好存在**该配置漂移，验证结果：

**启动日志**（不再静默）：
```
LLM preflight: [state] effective model 'local-model' (provider 'lmstudio')
not found among 41 served models — per-request calls will fail
```

**`GET /api/v1/metrics/providers`**：
```
ok=False  n_invalid_model=1  state_model='local-model'  state_model_present=False
alerts: critical state_invalid_model — 生效模型 'local-model'（provider 'lmstudio'）
        不在服务端模型列表中——每次请求都会失败（provider 自身配置可能正确，属配置漂移）
```

**Prometheus**：`more_os_provider_invalid_model 1`、
`more_os_provider_alerts{level="critical",code="state_invalid_model"} 1`。

> 即：此前静默杀死 Council 任务的故障，现在**启动即喊、看板可见、可告警、可抓取**。

---

## 7. 测试

`more_core/tests/test_provider_health_observability.py` —— **15 用例**：
provider 模型缺失检测、**生效模型漂移检测**、正常通过、快照往返 / 最新覆盖、
空快照容错、五类告警判定、JSON 端点、Prometheus 导出、按需复检写库。

> 测试要点：`TestClient` 的 lifespan 会调 `core.start()` 并记录一条启动快照，
> 涉及"最新快照"的用例需在其后播种。

---

## 8. 变更文件

- `more_core/more_core/governance/observability.py` — `provider_health_snapshots` 表 + record/query/alerts
- `more_core/more_core/llm/preflight.py` — 生效模型（state manager）校验
- `more_core/more_core/runtime/orchestrator.py` — 启动预检落库
- `more_core/more_core/api/routers/llm.py` — 按需复检写库
- `more_core/more_core/api/routers/monitor.py` — `/metrics/providers` + Prometheus 追加
- `more_core/more_core/api/metrics_dashboard.py` — Provider 健康卡片 + 告警合并
- `more_core/tests/test_provider_health_observability.py` — 新增测试

---

## 9. 待人工修复（环境侧）

代码已能**检出并告警**，但**根因仍在配置**：请把 `LLMCallState.model` 的默认占位符
`"local-model"` 改为实际模型（或将 state manager 初始 model 与 provider 配置对齐），
消除漂移。否则每次含 LLM 调用的请求仍会失败（现在至少会立刻告警而非静默）。

*执行人: Codex · 2026-10-05*
