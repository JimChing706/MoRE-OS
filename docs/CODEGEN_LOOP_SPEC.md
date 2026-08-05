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
