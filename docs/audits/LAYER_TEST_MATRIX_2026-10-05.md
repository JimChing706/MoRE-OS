# MoRE OS 分层架构综合测试案例设计（L0–L5）

**日期**: 2026-10-05
**目标**: 针对六层架构（L0 执行 / L1 编排 / L2 进化 / L3 符号 / L4 认知 / L5 元认知）组织**综合测试案例**，
覆盖契约、正常流、边界、异常降级、治理门控与跨层集成六个维度。
**现状基线**（设计前统计）：

| 层 | 现有用例 | 主要缺口 |
|----|:-------:|----------|
| L0 执行 | 88 | 与闸门/台账的**新链路**未覆盖 |
| L1 编排 | 26 | OMAC 4-tuple **契约负例**不足 |
| L2 进化 | 16 | 门控组合、DGM 失败降级缺失 |
| L3 符号 | 20 | 治理规则与**符号数学**的边界 |
| L4 认知 | 44 | 难度/能力写入契约、降级路径 |
| L5 元认知 | 17 | **访问控制**（blocked actor）、计划监控 |
| 跨层 | 6 | 路由 → 管道的**体系性验证**几乎空白 |

---

## 1. 设计方法

每层统一按下表六个维度设计用例（缺项即视为覆盖缺口）：

| 维度 | 代号 | 说明 |
|------|:----:|------|
| 契约 | C | `layer_id`、`run()` 返回类型、字段合法性 |
| 正常流 | H | 典型输入 → 预期产出 |
| 边界 | B | 空/超长/极端输入 |
| 异常降级 | E | 依赖缺失或失败时**不得崩溃**，须有明确降级 |
| 治理门控 | G | 开关关闭 / 权限不足时的行为 |
| 集成 | I | 与相邻层的契约（scratch 键、管道序列） |

---

## 2. 通用契约矩阵（C 维度，六层通用）

| ID | 用例 | 断言 |
|----|------|------|
| L-C1 | 每层可实例化 | 构造不抛异常 |
| L-C2 | `layer_id` 与注册表一致 | `core.get_layer(lid).layer_id == lid` |
| L-C3 | `run()` 返回 `LayerResult` 且 `result.layer == layer_id` | 类型/字段 |
| L-C4 | `run()` 追加一条 `ReasoningStep` | `len(accumulated_steps)` +1 且 `duration_ms >= 0` |
| L-C5 | 六层全部注册且无重复 | 注册表含 L0–L5 |

---

## 3. 分层用例设计

### 3.1 L0 执行层（ExecutionLayer）

| ID | 用例 | 前置 | 断言 |
|----|------|------|------|
| L0-H1 | 纯文本任务的正常产出 | 假 LLM | `output` 非空、`layer=L0` |
| L0-H2 | 代码任务提取并执行生成代码 | 假 LLM 返回代码块 | 沙箱执行成功或明确失败原因 |
| L0-B1 | 超长 query（>4K 字符） | — | 不崩溃，仍返回结果 |
| L0-E1 | LLM 全失败 → 结构化失败 | 注入 ConnectionError | `TaskStatus.FAILED` 且 output 含原因，非裸异常 |
| L0-G1 | 生成危险代码 → 交付闸门拦截 | 假 LLM 返回 `os.system` | `delivery_gates.passed=False` 或 verdict≠pass |
| L0-I1 | 阶段耗时写入 metadata | — | `metadata["stage_timings"]["layers_ms"]` 含 L0 |

### 3.2 L1 编排层（OrchestrationLayer）

| ID | 用例 | 断言 |
|----|------|------|
| L1-C1 | OMAC 4-tuple 合法 | `_validate_omac_output` → (True, ok) |
| L1-C2 | 缺 key | → False，reason 含 "missing key" |
| L1-C3 | `token_budget` 类型错（bool/str） | → False |
| L1-C4 | `token_budget <= 0` | → False |
| L1-C5 | 非法 mode / strategy / model_hint | → False（三种各一例） |
| L1-H1 | 正常任务产出策略 | scratch 含 mode/strategy/temperature |
| L1-B1 | 未知/自定义 TaskType | 不崩溃，仍有默认策略 |
| L1-I1 | 策略参数供下游消费 | scratch 的 temperature/token 预算存在 |

### 3.3 L2 进化层（EvolutionLayer）

| ID | 用例 | 断言 |
|----|------|------|
| L2-G1 | 默认关闭（evolution=False） | `output["evolved"]=False`，description 含 disabled |
| L2-G2 | 全局开但 request 不允许自改进 | 仍禁用（双重门控） |
| L2-E1 | DGM 抛错 | 不崩溃；返回明确失败/降级说明 |
| L2-I1 | 关闭时不触碰 DGM | 不应调用 snapshot（用 Mock 断言） |

### 3.4 L3 符号层（SymbolicLayer）

| ID | 用例 | 断言 |
|----|------|------|
| L3-H1 | 普通 query 治理通过 | `output["violations"]` 空 |
| L3-G1 | 危险 query（`rm -rf`） | 规则命中（violations 非空）或抛 GovernanceError |
| L3-H2 | MATH_REASONING → SymPy 计算 | `scratch["symbolic_result"]` 被写入，description 含 symbolic math |
| L3-B1 | 超长 query 触发长度规则 | violations 非空 |
| L3-I1 | 注解供 L0 使用 | `scratch["inference_annotations"]` 存在 |

### 3.5 L4 认知层（CognitionLayer）

| ID | 用例 | 断言 |
|----|------|------|
| L4-H1 | 写入 difficulty/capability | scratch 两键均为 int 且范围 0–10 |
| L4-H2 | 长 query 难度上升 | difficulty ≥ 短 query 的 difficulty |
| L4-B1 | 空 query | 不崩溃，仍产出 plan |
| L4-I1 | 结构化计划供 L5 监控 | `scratch["plan"]` 存在且含 subtasks |

### 3.6 L5 元认知层（MetacognitionLayer）

| ID | 用例 | 断言 |
|----|------|------|
| L5-H1 | 正常 actor → 校准 | `scratch["calibration"]` 含 alignment |
| L5-G1 | 被阻断 actor | `output["blocked"]=True`、confidence=0、description 含 DENIED |
| L5-G2 | 阻断时记事故 | incident manager 被调用（Mock 断言） |
| L5-I1 | 有 plan 时做计划监控 | `scratch["plan_health"]` 被写入 |

### 3.7 跨层集成（Router / Pipeline）

| ID | 用例 | 断言 |
|----|------|------|
| X-I1 | 六层注册完整 | `{L0..L5} ⊆ 注册表` |
| X-I2 | 各 TaskType 路由到非空管道 | pipeline 非空且全部已注册 |
| X-I3 | SELF_IMPROVEMENT 管道含 L5/L2 | 顺序 L5→L2→L1→L0 |
| X-I4 | MATH_REASONING 管道含 L3/L4 | — |
| X-I5 | 端到端：一次真实执行产出完整 TaskResult | status/output/reasoning_chain 均有值，且阶段耗时齐全 |
| X-I6 | 执行失败可诊断 | FAILED 时 output/error 含原因，不静默 |

---

## 4. 验收标准

1. 上表全部用例实现为可运行测试（`more_core/tests/test_layer_matrix_l0_l5.py`）。
2. **全部通过**；失败项须判定为"产品缺陷"或"设计修正"，不得跳过。
3. 覆盖率：L2/L5 用例数较基线 **+50%**，跨层用例 **≥6**。
4. 输出分层通过矩阵报告。

## 5. 执行约定

* 复用 `conftest.py` 的 `core` fixture（已注册内置工具 + 假 LLM，离线可跑）。
* 涉及外部模型的用例一律用假 provider，保证**可重复、无网络依赖**。
* 治理门控类用例必须同时验证"关闭时确实不执行危险动作"。

---

*设计人: Codex · 2026-10-05*

---

## 6. 执行结果矩阵（2026-10-05 实测）

**测试文件**: `more_core/tests/test_layer_matrix_l0_l5.py` — **72 个用例，全部通过**（0.47s，离线）。
**全量回归**: `pytest tests/` → **1394 passed**（基线 1322 + 本次 72），0 失败。

### 6.1 分层落地情况

| 层 | 设计用例 | 用例函数 | 收集实例 | 结果 |
|----|:-------:|:-------:|:-------:|:----:|
| 通用契约 L-C1..C5 | 5 | 3 | 13（参数化 ×6 层） | ✅ |
| L0 执行 | 6 | 6 | 6 | ✅ |
| L1 编排（OMAC 契约） | 8 | 8 | 18（token/enum 参数化） | ✅ |
| L2 进化 | 4 设计 + 4 深化 | 8 | 8 | ✅ |
| L3 符号 | 5 | 4（I1 并入 H1 断言） | 4 | ✅ |
| L4 认知 | 4 | 4 | 4 | ✅ |
| L5 元认知 | 6 设计 + 3 深化 | 9 | 9 | ✅ |
| 跨层集成 X-I1..I6 | 6 | 6 | 10（TaskType 参数化） | ✅ |
| **合计** | — | **48** | **72** | ✅ 72/72 |

### 6.2 发现的缺陷与处置（区分产品缺陷 / 设计修正）

| # | 用例 | 现象 | 判定 | 处置 |
|---|------|------|------|------|
| 1 | L2-E1 | `dgm.snapshot()` 抛错时异常击穿主管道 | **产品缺陷**（可用性/安全） | 在 `EvolutionLayer.process` 包裹演进周期，异常→降级 `evolved=False, degraded=True, error=...`，并记事故；见 `layers/l2_evolution.py` |
| 2 | L5-E1 | `metacognition.maybe_self_modify()` 抛错击穿主管道 | **产品缺陷**（与 #1 同类） | 在 `MetacognitionLayer.process` 包裹自修改调用，异常→`self_modification_error` 写入 scratch 与 output，主管道继续；见 `layers/l5_metacognition.py` |
| 3 | L3-G1 | 用户直接请求 `执行 rm -rf /` 时治理规则**不命中**（旧规则只扫 `code_output` 事实，不扫入站 query） | **产品缺口**（治理门控） | 新增 `destructive_request_detection` 规则，窄正则覆盖 `rm -rf/fr`、`mkfs`、`dd of=/dev/`、fork bomb、裸设备重定向；高危→violation；见 `ontology/rule_engine.py` |
| 4 | L3-B1 | 超长 query 在 `strict_ontology=True` 下抛 `GovernanceError` | **设计修正** | 规则本身生效（CRITICAL 拦截）；测试改为同时接受"抛错"与"violations 非空"两种契约 |
| 5 | X-I3 | 默认 `enable_evolution/enable_metacognition=False` 时路由剥离 L5/L2 | **设计修正** | 顺序断言前显式开门；新增 X-I3b 验证"关门时确实剥离"（门控契约本身） |

> 缺陷 #1/#2 属同一根因：**非关键、opt-in 的自演进/自修改子系统缺少故障隔离**——
> 一旦其依赖（DGM / HyperAgent）故障，本应"降级"却"击穿"主任务链路。两处已统一为
> 包含式（containment）降级，并把降级原因写入 `metadata`/`scratch` 以便可观测。

### 6.3 覆盖率验收

| 指标 | 基线 | 目标 (+50%) | 交付 | 达标 |
|------|:----:|:-----------:|:----:|:----:|
| L2 用例 | 16 | ≥24 | **24** | ✅ |
| L5 用例 | 17 | ≥26 | **26** | ✅ |
| 跨层用例 | 6 | ≥6 | **12**（矩阵 6 + `test_layers.py` 6） | ✅ |

### 6.4 变更文件

- `more_core/more_core/layers/l2_evolution.py` — DGM 故障隔离
- `more_core/more_core/layers/l5_metacognition.py` — 自修改故障隔离
- `more_core/more_core/ontology/rule_engine.py` — 破坏性请求治理规则
- `more_core/tests/test_layer_matrix_l0_l5.py` — 新增 72 用例（本矩阵）
- `docs/audits/LAYER_TEST_MATRIX_2026-10-05.md` — 本设计书 + 执行结果

---

## 8. 回顾性检验（2026-10-05）

后续系统增强后对本矩阵做了**回顾性检验**，结论：
* L0–L5 单层契约与故障隔离用例**依然全部有效**（72/72 全绿）。
* ⚠️ X-I2 / X-I3 / X-I4 原断言 `core.router.route()`，但它是**非权威来源**——
  生产实际执行由 **Meta-Orchestrator 谱路由**决定。
  **→ 已迁移**：X-I2/I3/I3b/I4 现断言 `core.meta_orchestrator.route()`，并修正了三处
  原本不成立的契约（SELF_IMPROVEMENT 不含 L5/L2、L2 全链路不可达、L3 由谱模式决定）。
* 权威链路由 `test_layer_matrix_retrospective.py`（17 用例）持续钉住。

详见: [LAYER_MATRIX_RETROSPECTIVE_2026-10-05.md](LAYER_MATRIX_RETROSPECTIVE_2026-10-05.md)

---

*执行人: Codex · 2026-10-05*

---

## 7. CI 门禁接入（PR 必跑）

为把上述矩阵固化为止损线，已将分层用例纳入 CI，并提供本地同源入口。

### 7.1 新增 CI Job

`.github/workflows/ci.yml` 新增独立 job **`Layer Matrix Gate (L0-L5)`**（`layer-gate`），
触发条件与既有 workflow 一致（`push: main/develop`、`pull_request: main`）。两步：

1. `pytest tests/test_layer_matrix_l0_l5.py -q --tb=short` —— **72 用例**分层矩阵。
2. `pytest tests/ -m fault_isolation -q --tb=short` —— 跨全仓的**故障隔离回归**（标注该 marker 的用例）。

`docker-build` 的 `needs` 已加入 `layer-gate`，使该门禁成为阻塞式检查。

### 7.2 测试标记（pytest marker）

在 `more_core/pytest.ini` 注册两个标记，避免 `-m` 选择产生未知标记告警：

| 标记 | 含义 | 覆盖 |
|------|------|------|
| `layer_matrix` | L0–L5 分层架构综合测试矩阵 | `test_layer_matrix_l0_l5.py` 全模块（模块级 `pytestmark`） |
| `fault_isolation` | 自演进/自修改故障隔离回归 | L2-E1、L2-E2、L5-E1 三个包含式降级用例 |

> 注：仓库实际生效的是 `more_core/pytest.ini`（`pyproject.toml` 的 pytest 段被忽略），
> 故标记注册在 `pytest.ini`。

### 7.3 本地同源入口

```bash
make test-layers     # 与 CI layer-gate 完全同源：矩阵 + 故障隔离
make check           # lint + typecheck + 全量 test + test-layers
```

### 7.4 门禁有效性验证（负向测试）

为证明门禁"真能拦"，做了受控回退实验：

| 步骤 | 操作 | 观察 |
|------|------|------|
| 1 | 备份 `l2_evolution.py`（sha256 记录） | 13f016a6… |
| 2 | 临时移除 L2 的 try/except 故障隔离 | — |
| 3 | 跑 `pytest tests/ -m fault_isolation` | **2 failed**（L2-E1、L2-E2）——门禁拦截成功 |
| 4 | 从备份还原并校验 sha256 | OK，`git diff` 为空 |
| 5 | 重跑 `make test-layers` | 72 passed + 3 passed —— 恢复通过 |

结论：一旦 L2/L5 的包含式降级被回退，PR 门禁会立即变红，回归无法合入。

### 7.5 待人工配置（仓库外）

GitHub 分支保护需管理员在 **Settings → Branches → Branch protection rules** 中把
`Layer Matrix Gate (L0-L5)` 勾选为 **required status check**；此属仓库设置，无法由代码提交完成。

*执行人: Codex · 2026-10-05*
