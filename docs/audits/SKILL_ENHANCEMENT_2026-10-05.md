# Skill 功能增强与优化（2026-10-05）

**目标**: 对 `more_core/skills` 技能子系统做正确性 / 可用性 / 可观测性增强。
**范围**: `skills/base.py`（SkillManager）、`governance/observability.py`、
`api/routers/skills.py`、`api/routers/monitor.py`、`api/metrics_dashboard.py`。

---

## 1. 审计发现的 7 个问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | `execute()` **从不更新** `usage_count` / `success_rate` / `avg_duration_ms` | 元数据恒为初值（usage=0、rate=1.0）→ 看板全是**假数据** |
| 2 | `on_error` 钩子在 `_hooks` 里定义却**从未被调用** | 错误处理钩子形同虚设 |
| 3 | `execute()` 无异常隔离，技能内部异常直接向上抛 | 单个技能异常击穿调用方 |
| 4 | 无超时保护 | 挂死的技能会永久阻塞 |
| 5 | `start_all()` **从未在启动时调用**（`bootstrap` 只 register） | 全部技能恒为 `INACTIVE`，`health_check()` 恒 `False`（面板全"未激活"） |
| 6 | `register()` 重复 id 会向分类列表追加重复项 | 分类计数错乱 |
| 7 | 技能执行**无任何遥测/端点/看板** | 无法回答"哪些技能在跑、成功率多少、多慢" |

---

## 2. 增强内容

### 2.1 `SkillManager.execute()` 重写

* **错误隔离**：技能异常 → `SkillResult(success=False, error="ErrorType: msg")`，不向外抛。
* **超时保护**：`SkillManager(timeout_s=...)`，默认 120s（`MORE_SKILL_TIMEOUT_S` 可覆盖）；
  超时 → 结构化失败 `skill timed out after Ns`。
* **返回值校验**：技能返回非 `SkillResult` → 结构化失败。
* **真实指标**：每次执行累计更新 `usage_count` / `success_rate` / `avg_duration_ms`。
* **`on_error` 钩子**：失败时触发（钩子自身异常不影响结果）。
* **遥测落库**：写入 `governance.observability` 的 `skill_runs` 表（不可用则静默）。

### 2.2 生命周期修复

* `start_all()` / `stop_all()` 逐技能 try/except（单个失败不阻断全体）。
* `MoRECore.start()` 调用 `skill_manager.start_all()` → 技能真正 `ACTIVE` / `healthy`。

### 2.3 遥测与对外接口

| 能力 | 落地 |
|------|------|
| 遥测表 | `skill_runs`（skill_id/category/success/duration_ms/error） |
| 聚合 | `query_skill_stats(window_s)`：runs / success_rate / avg / **p95** / by_skill / by_category |
| JSON 端点 | `GET /api/v1/metrics/skills` |
| Prometheus | `more_os_skill_runs`、`more_os_skill_success_rate`、`more_os_skill_avg_duration_ms`、`more_os_skill_runs_by_skill{skill,result}` |
| 技能 API | `GET /skills` 增加 `status/usage_count/success_rate/avg_duration_ms/author/dependencies`；新增 `GET /skills/{id}`（含 `healthy`） |
| 看板 | 新增「技能执行 / 技能成功率」卡片 |

---

## 3. 实机验证

| 验证 | 结果 |
|------|------|
| `/skills` 状态 | 修复前 `active=0` → 修复后 **`active=5/5`**，全部 `status=active` |
| 技能详情 | `code.execute` → `status=active, healthy=True` |
| 实机执行 | `POST /skills/code.execute/run {"code":"print(1+1)"}` → `success=True, output='2\n', duration_ms=22.1` |
| 遥测 | `/metrics/skills` → `runs=1, success_rate=1.0, avg=22.1ms, p95=22.1ms`，`by_skill` 正确 |

---

## 4. 测试

`more_core/tests/test_skill_execution.py` —— **14 用例**：
指标累计（成功/失败）、异常隔离 + on_error、超时、非 SkillResult 拒绝、
校验失败计数、遥测落库、注册表统计、重复注册去重、未知技能、
`start_all` 失败隔离、`core.start()` 激活默认技能、`/metrics/skills`、
`/skills` 列表与 `/skills/{id}` 详情。

---

## 5. 变更文件

- `more_core/more_core/skills/base.py` — execute 重写 + 指标 + 遥测 + 启停加固
- `more_core/more_core/governance/observability.py` — `skill_runs` 表 + record/query
- `more_core/more_core/api/routers/skills.py` — 列表增强 + 详情端点
- `more_core/more_core/api/routers/monitor.py` — `/metrics/skills` + Prometheus
- `more_core/more_core/api/metrics_dashboard.py` — 技能卡片
- `more_core/more_core/runtime/orchestrator.py` — 启动时 `start_all()`
- `more_core/tests/test_skill_execution.py` — 新增 14 用例

*执行人: Codex · 2026-10-05*
