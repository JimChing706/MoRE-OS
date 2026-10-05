# 分层测试矩阵 —— 回顾性检验报告

**日期**: 2026-10-05
**对象**: `docs/audits/LAYER_TEST_MATRIX_2026-10-05.md` 及 `more_core/tests/test_layer_matrix_l0_l5.py`
**动机**: 系统此后经历多次增强（LLM 调度、Council 降载、技能子系统、可观测性），
需**回顾性检验**早期分层用例是否仍然成立、是否有假保障。

---

## 1. 复跑结果

| 套件 | 用例 | 结果 |
|------|:----:|:----:|
| `test_layer_matrix_l0_l5.py`（L0–L5 + 跨层） | 72 | ✅ 全绿 |
| `test_layers.py`（既有跨层） | 6 | ✅ 全绿 |
| **回顾性新增** `test_layer_matrix_retrospective.py` | 17 | ✅ 全绿 |

早期 5 项缺陷修复**均仍生效**（L2/L5 故障隔离、L3 破坏性治理、X-I3 门控）——
对应 `fault_isolation` 标记用例持续通过。

---

## 2. 回顾性核心发现：**基座路由不是权威来源**

### 2.1 现象

对同一请求，`core.router.route()` 声明的管道与**实际执行**不一致：

| TaskType | 基座 `router.route()` | 实际执行 | 一致 |
|----------|:---------------------:|:--------:|:----:|
| nlp_task | `L4,L3,L1,L0` | `L4,L1,L0` | ❌ |
| code_generation | `L4,L3,L1,L0` | `L4,L3,L1,L0` | ✅ |
| multi_agent_orchestration | `L4,L1,L0` | `L4,L3,L1,L0` | ❌ |
| self_improvement | `L1,L0` | `L4,L3,L1,L0` | ❌ |

既有**跳过**也有**新增** —— 说明二者是两套独立机制。

### 2.2 根因

`MoRECore` 启用了 **Meta-Orchestrator 谱路由**，其决策**完全覆盖**基座路由：

```python
# runtime/orchestrator.py
if self.meta_orchestrator is not None:
    decision = meta_decision          # 完全覆盖
    ...
else:
    decision = self.router.route(request, available_providers=available)
```

谱模式（按不确定性 U）：
* **VILLAGE**（U < 0.3）→ `[L4, L1, L0]`（轻量，**跳过 L3**）
* **RIVER**（U ≥ 0.3）→ `[L4, L3, L1, L0]`（含 L3）

### 2.3 影响

* **测试假保障**：矩阵的 X-I2 / X-I3 / X-I4 断言的是 `core.router.route()`，
  而这**不是生产实际执行的来源** → 这些用例通过 ≠ 实际路由正确。
* **文档误导**：`DEFAULT_PIPELINES`（基座路由表）被当作"系统管道"阅读，实际不生效。
* 好消息：实际执行**本身是自洽且确定**的 —— 实测
  `metadata.stage_timings.layers_ms` == `meta_orchestrator.route().pipeline`（逐项一致）。

---

## 3. 回顾性新增用例（17）

| 用例 | 钉住的契约 |
|------|-----------|
| `test_executed_pipeline_matches_meta_orchestrator`（×5 类型） | **权威**：实际执行 == 谱路由决策 |
| `test_stage_timings_cover_every_executed_layer`（×5） | D-4：每个执行层有耗时留痕，且与 reasoning_chain 一致 |
| `test_l0_always_runs_last_and_all_layers_registered`（×5） | L0 必执行且居末；执行层均已注册 |
| `test_mode_determines_l3_inclusion` | L3 由**谱模式**决定，非任务类型 |
| `test_base_router_diverges_from_authoritative_pipeline` | **登记已知分歧**，防止静默漂移 |

---

## 4. 结论与建议

### 结论
* 分层**单层契约与故障隔离**用例依然有效（72/72 全绿）。
* 分层**路由→执行**用例存在**假保障**：断言对象（基座路由）非权威。
* 实际执行链路自洽、可观测（`stage_timings` 即真相），已用 17 个回顾性用例钉住。

### 建议（待决策）
1. **对齐语义**：让 `LayerRouter` 成为谱路由的降级实现，或明确标注其为"advisory"，
   避免继续被误读为权威管道。
2. **改造矩阵**：把 X-I2/I3/I4 的断言对象从 `core.router.route()` 改为
   `meta_orchestrator.route()`（或直接断言 `stage_timings`）。
3. **CI 门禁**：把本回顾性套件纳入 `layer-gate`（`make test-layers`），防止分歧漂移。

---

## 5. 变更文件

- `more_core/tests/test_layer_matrix_retrospective.py`（新增 17 用例）
- 本报告

*执行人: Codex · 2026-10-05*
