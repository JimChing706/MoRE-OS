# MoRE OS 代码自动生成 Agentic Loop 流程规范 (BPR)

**版本**: 1.0 · **日期**: 2026-08-04 · **框架**: OpenAI Agents SDK (`openai-agents`) Runner Agent Loop

## 1. 目标与范围

对 MoRE OS 的"基础功能代码自动生成"环节做业务流程再造：从"一次性单智能体生成"升级为
**多智能体、受控循环、强制自检、强制自审计、最终固定落盘** 的流水线。本规范定义流程本身；
`scripts/codegen_loop.py` 将其固化为可执行控制器；本仓库的任何功能生成都走此流程。

## 2. 流程总览（Agentic Loop）

```
                 ┌────────────────────────────── LOOP (max_iterations=N) ─────────────────────────────┐
                 │                                                                                      │
 [Controller]    [Generator]        [Self-Check]            [Self-Audit]            [Fix]               │
  定义任务  ──▶  LLM/子代理生成   ─▶  编译+测试+lint       ─▶ 代码评审(安全/质量)  ─▶ 修复回灌         │
  失败标准         代码/测试           全绿?                    无 P1/P2?            (缺陷输入)          │
     │              │                    │                          │                     │             │
     └──────────────┴────────────────────┴────── 任一不通过 ───────┴─────────────────────┘             │
                                                     │ 全部通过                                          │
                                                     ▼
                                              [Lock] 固定落盘
                                          Conventional Commits + 审计记录
```

## 3. 角色与映射

| 角色 | 职责 | MoRE OS 层映射 |
|------|------|----------------|
| Controller | 定义任务/成功标准/循环上限，裁决退出 | L5 Metacognition |
| Generator | 产出代码 + 测试（先测试后实现的 TDD 模式） | L4 Cognition + L3 Symbolic |
| Self-Check | 编译/类型/lint/单测，用代码回答"是否绿" | L1 Orchestration (工具执行) |
| Self-Audit | 安全/质量/一致性评审，产出缺陷清单 | L2 Evolution (benchmark 驱动) |
| Lock | 提交 + 生成审计记录 | L0 Execution (git) |

## 4. 循环控制（Loops 控制）

- **迭代上限**: `max_iterations`（默认 3）。生成/修复/自检/自审计为一轮。
- **退出条件（全部满足）**:
  1. Self-Check 全绿：后端 `pytest`、前端 `vitest`、`lint`、`tsc`、`build`。
  2. Self-Audit 无 P1/P2 缺陷；P3 允许带说明放行。
  3. 相对上次迭代存在真实进展（否则防死循环提前终止）。
- **升级**: 超上限未达标 → 降级为 P0 人工接管，保留全部中间产物（plan/check/audit 记录）。
- **实现**: 依赖 `openai-agents` `Runner.run()` 的 agent loop（max_turns）+ 本控制器的手写外层循环。

## 5. 产物与落盘（Lock）

- **代码**: 按模块边界落盘，测试与实现同 PR/commit。
- **审计记录**: `docs/CODEGEN_RUNS/` 下每次运行一份 `run_<ts>.md`（任务、迭代轨迹、检查/评审结果、提交 hash）。
- **提交规范**: Conventional Commits；消息含功能域（`feat(governance):`/`feat(frontend):` 等）。
- **质量门禁**: `make test-cov`（cov ≥ 50%）与前端 `lint/tsc/build` 必须通过才允许 Lock。

## 6. 与既有 L 层的关系

本流程是 L2 自我进化与 L5 元认知的**执行实例**：Controller 即轻量元认知层，
Self-Audit 结果可回灌 evolution 基准。流程本身作为服务沉淀，不替代既有 orchestrator。

## 7. 首个实例（基准切片）

| 项 | 值 |
|----|----|
| 任务 | 端到端垂直切片：Live Audit Log Viewer |
| 后端 | `GET /api/v1/security/audit`（已存在，补功能测试） |
| 前端 | `moreEngine.ts` 接入 audit 响应、`SafetyPanel` 渲染真实记录、类型补全 |
| 验收 | 后端 735+ 用例、前端 36+ 用例、lint/tsc/build 全绿 |

## 8. 管道内闭环：L0 修复循环 + 自检（v0.9.9, 2026-08-05）

BPR 的 Agentic Loop 已下沉为运行时管道内的**自动闭环**，不依赖外部 `codegen_loop.py` 控制器：

### 8.1 L0 代码修复循环（`layers/l0_execution.py`）

```
生成 ──▶ 安全检查(L3/正则) ──▶ python_exec 沙箱执行 ──┐
    ▲                                               │ 失败
    └──── 修复重生成(携 stderr, ≤3 轮, temp=0.4) ─────┘
                │ 成功
                ▼
         code_fix_output 替换最终 output
```

- 常量 `_MAX_CODE_FIX_ROUNDS = 3`；`_FIX_DIRECTIVES` 强制 LLM 直接输出修复代码
- 范围覆盖 `CODE_GENERATION`/`CODE_DEBUGGING`/`CODE_TESTING`（scope=code/test）
- 每轮迭代审计：`AuditLogger.log(action="code_fix_iteration", round, success, error)`
- 层描述包含 `code fix loop (N/3)`，供推理链/可观测性展示

### 8.2 管道输出自检（`runtime/orchestrator.py:_complete_task()`）

- 复用 `council/self_check.py:run_pipeline_self_check()`（原先为死代码）
- 对推理链 → 最终输出做启发式覆盖度审计，结果写入 `TaskResult.metadata["self_check"]`
- `backfill_required` 时审计 `self_check_backfill`；**advisory**，异常不影响任务状态

### 8.3 Evolution 基准种子（`evolution/benchmark.py`）

- `SimpleBenchmark()` 无显式套件时回退到 `DEFAULT_SUITE`（`code_fib`/`code_sort`/`code_hello`）
- 修复 DGM/L2 评估空套件 → 全部变体静默拒绝的问题

### 8.4 验证

- `test_l0_execution.py`：`TestRunFixLoop`（7）+ `TestBuildFixPrompt`（2）+ 端到端 `test_fix_loop_end_to_end`（真实 python_exec + `_FailingThenFixedProvider`）
- `test_orchestrator.py::test_self_check_written_to_metadata`
- `test_benchmark.py`：默认套件种子 + code_fib 命中
- `make lint` / `make typecheck` 全绿，`make test` → **756 passed**（此前 743）

## 9. 链路系统评估与改进（v0.9.10, 2026-08-06）

### 9.1 评估结论（对标前沿高效代码生成 LLM 链路）

| 环节 | 现状 | 对标标准（AlphaCodium / SWE-agent / TDD codegen） | 差距 |
|------|------|----------------|------|
| 任务分类 | 关键词 AUTO→code_generation | 零成本确定性分类 | ✅ 已对齐 |
| 规划 | L4 难度估计 + LLM/council 子任务 | plan-then-code | ✅ 已对齐 |
| 生成 | code_primary 链 + 并行竞速 | 任务感知模型路由 | ✅ 已对齐 |
| 提取 | 仅 ```python 围栏正则 | 结构化输出 JSON | ❌ 脆弱 |
| 验证 | 沙箱"能跑"即成功 | **行为验证：断言/测试全绿** | ❌ 最大差距 |
| 自检 | 关键词覆盖启发式 | 任务类型感知 | ❌ 代码任务固定报 0% |

### 9.2 改进（本轮落地）

1. **多策略代码提取**（`l0_execution.py:_extract_python`）— 结构化 JSON `{"code":...}` → 围栏 → 可编译裸代码三级回退，修复"中英文夹杂输出导致漏提取"。
2. **断言验收（TDD 式行为验证）**（`_run_fix_loop(assertions=...)`）— 请求 `context["assertions"]` 注入验收断言，生成代码与断言合并为单程序执行；断言失败即视为失败并回灌 LLM 修复循环，成功标准从"能跑"升级为"行为正确"。
3. **任务类型感知自检**（`council/self_check.py:run_pipeline_self_check(task_type=)`）— 代码任务有可执行产物即视为 100% 覆盖，修复旧逻辑对代码输出固定 0% 覆盖的误报。

### 9.3 验证

- `test_l0_execution.py`：新增提取 6 例 + 断言修复循环 4 例
- `test_self_check.py`：新增文本/代码双分支 10 例
- `make test` → **818 passed**（此前 799），`make lint` / `make typecheck` 全绿
- 实跑：`is_even` 任务（auto→code_generation，3 断言全过）L0=`code executed + assertions verified`，conf=0.95，self_check=`100.0 / 代码产物完整`

## 10. 流程再造：仓库上下文注入 + 闭环控制（B/D，2026-08-06）

在 §9 链路改进基础上做流程再造，方向 B（仓库上下文注入）与 D（闭环控制）。

### 10.1 B — 仓库感知生成（`codegen/context.py`）

- `build_repo_context(project_root, max_files=30)`：扫描项目根，产出紧凑仓库地图（模块相对路径 :: 顶层 def/class/路由），输出 `<repo_context>` 块；任何失败/无模块 → 空串，可无条件追加。
- 注入点：`l0_execution.py:process()` 对 code 类任务，在 tool schemas 之后向 system prompt 追加仓库地图；层描述出现 `repo context`。
- 开关：`MORE_CODEGEN_CONTEXT`（默认 1）；`Settings.project_root` 默认取 CWD（`make start` 即仓库根），文件工具根固定化，行为与原先 cwd 回退一致。
- 无项目根（如单测 core fixture）→ 注入跳过，测试零耦合。

### 10.2 D — 闭环控制（`l0_execution.py`）

1. **确定性修复前置**（`_deterministic_fix`）：纯静态修复，仅触碰语法/编码层，绝不改语义——
   BOM/CRLF 归一、整块去缩进（程序整体意外缩进）、截断修剪（尾部杂文/未闭合截断）。语法类错误零 LLM 轮修复；语义错误仍交给 LLM。
2. **收敛检测**：`_MAX_CODE_STAGNANT_ROUNDS=2`，连续两轮代码+错误均不变 → 提前终止，置 `{scope}_fix_stagnant`，审计 `code_fix_converged`，层描述出现 `fix stalled`。
- 修复成功时 `{scope}_fix_output` 替换最终 output；层描述含 `deterministic repair`。

### 10.3 验证

- `test_l0_execution.py`：新增确定性修复 4 例（含零 LLM 轮端到端 + 停滞提前终止）+ `_deterministic_fix` 3 例
- `test_codegen_context.py`：新增 7 例（空根/模块扫描/噪声目录/文件数上限/L0 注入开关）
- `make test` → **830 passed**，`make lint` / `make typecheck` 全绿（181 源文件）
