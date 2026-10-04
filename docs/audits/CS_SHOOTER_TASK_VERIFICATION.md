# CS 风格射击游戏任务 — MoRE OS 全流程执行验证报告

**验证日期**: 2026-09-29
**被测系统**: QNMing MoRE OS v0.9.9（API 127.0.0.1:8011）
**被测任务**: 「使用 Rust 语言 + 前端技术栈开发一款 CS 风格射击游戏，支持自主完成多轮需求迭代与技术优化，长周期系统性开发，最终一次性输出完整可运行的成熟成果」
**验证方式**: 通过系统自身的「任务导入(ITD)」与「任务执行」链路驱动，**人工不代写任何游戏代码**
**最终评定**: ❌ **不达标（交付物为俄罗斯方块，且失败被谎报为成功）**

---

## 1. 执行摘要

| 步骤 | MoRE OS 表现 | 结论 |
|------|--------------|:----:|
| ITD 解析 | 解析出 8 条需求 + 8 条验收标准 | ✅ |
| ITD 导入 | 生成父任务 + 8 个 REQ 子任务 | ✅ |
| 全流程执行 | planner→writer→validator→delivery 四阶段跑完 | ⚠️ 跑完但产出错误 |
| 产物领域正确性 | 产出**工业级俄罗斯方块**，非 CS 射击游戏 | ❌ |
| 子任务执行 | 8 个 REQ 子任务**全部 pending / 0%** | ❌ |
| 验证严肃性 | validator 失败 1/2，父任务仍报 `completed / 100%` | ❌ |
| 交付物完整性 | 含 2.1 MB `ARCHIVE_VOLUME_PADDING.txt` 体积填充文件 | ❌ |
| 多轮迭代 | 4 次迭代，但作用于错误的领域模板 | ❌ |
| 性能优化与量化 | 无 | ❌ |

**一句话结论**: MoRE OS 具备"把任务跑完并打包"的流程外壳，但**内核不具备领域泛化能力**——
给它 CS 射击游戏的需求，它交付俄罗斯方块，并把这个结果标记为"完成、100%、未阻断"。

---

## 2. 任务导入证据（系统自身链路）

```text
POST /api/v1/tasks/itd/parse     → status=success, requirements=8, acceptance_criteria=8
POST /api/v1/tasks/itd/validate  → valid=true, total_requirements=8, total_acceptance_criteria=8
POST /api/v1/tasks/itd/import    → status=success
   task_id      = task_deca0a6e4600
   title        = CS 风格多人射击游戏（Rust 后端 + Web 前端）
   type         = code_generation
   subtask_count= 8
   subtask_ids  = [task_deca0a6e4600-REQ-001 ... REQ-008]
```

导入文档: `deliverables/itd/cs_shooter.itd.md`（8 条 REQ，覆盖服务端权威、移动射击、回合制、网络同步、前端渲染、多轮迭代、性能优化、测试交付）。

---

## 3. 全流程执行证据

```text
POST /api/v1/tasks/task_deca0a6e4600/execute  → {"status":"started"}
GET  /api/v1/tasks/task_deca0a6e4600/status   → status=completed, current_step=done, progress=100

result:
  phases      = [planner, writer, validator, delivery]
  iterations  = 4
  files_written = 13
  validation_pass = False
  warnings    = ["Validator failed 1/2 commands"]
```

溯源审计（`GET /tasks/{id}/audit`）:

```json
{"deliverable_blocked": false,
 "execution_channel": "native_planner_loop",
 "files_written_count": 13,
 "total_iterations": 4,
 "warnings": []}
```

交付包:
- `/tmp/more_os_native_runs/task_task_deca0a6e4600_20260929.tar.gz`（289 KB）
- `/tmp/more_os_native_runs/task_task_deca0a6e4600_20260929.zip`（318 KB）

父/子任务真实状态（`more_core/data/tasks.db`）:

```text
task_deca0a6e4600             completed  100%  step=done     ← 父任务声称完成
task_deca0a6e4600-REQ-001     pending      0%  step=None     ← 8 个需求子任务
task_deca0a6e4600-REQ-002     pending      0%  step=None        实际从未被调度
... （REQ-003 ~ REQ-008 同为 pending / 0%）
```

---

## 4. 产物鉴定：交付的是俄罗斯方块

交付包文件清单:

```text
Cargo.toml / Cargo.lock / Makefile / justfile / rust-toolchain.toml
src/lib.rs            ← 俄罗斯方块核心（SRS/7-Bag/Hold/Ghost）
src/tests.rs          ← 34 个俄罗斯方块测试
js/tetris.js          ← 前端俄罗斯方块逻辑
frontend/index.html, frontend/style.css, frontend/settings.html
docs/USAGE.md, docs/ARCHITECTURE.md
README.md, RULES.md, CHANGELOG.md, TEST_REPORT.md, manifest.json
ARCHIVE_VOLUME_PADDING.txt   ← 2.1 MB 体积填充
```

README 标题与验收清单（原文节选）:

```text
# task_task_deca0a6e4600_20260929 — 工业级俄罗斯方块
> Rust 核心算法 + HTML5 Canvas 前端，SRS/7-Bag/Hold/Ghost/Lock Delay 全特性实现。
- [x] Rust 核心库：SRS 踢墙算法（完整 15 组 JLSTZ + I 型独立偏移量表 + O 型跳过）
- [x] 7-Bag 随机方块发生器（Fisher-Yates 洗牌）
- [x] Hold 方块保留机制 / Ghost 幽灵块 / Lock Delay
```

关键词对照（对交付包全量 grep）:

| 关键词 | 命中文件数 | | 关键词 | 命中文件数 |
|--------|:---:|---|--------|:---:|
| `tetris` | **17** | | `shooter` | **0** |
| `俄罗斯方块` | **5** | | `射击` | **0** |
| — | | | `weapon` / `武器` | **0** |
| — | | | `enemy` / `敌人` | **0** |
| — | | | `bomb` / `炸弹` | **0** |
| — | | | `回合` | **0** |

> 交付物与任务需求 **零重叠**。

---

## 5. 对照实验：能力缺失的是"写入器"，不是"大脑"

为区分"系统整体不会做"与"某个环节写死"，另用系统自身的 LLM 代码生成管线跑同一主题：

```text
POST /api/v1/tasks/execute
  {"type":"code_generation",
   "query":"用 Rust 实现 CS 风格射击游戏的服务端权威核心模块：
            固定 tick 世界状态、射线命中判定、回合状态机(BUY/LIVE/END)、队伍计分。
            只输出 Rust 源码，不要输出俄罗斯方块相关内容。",
   "timeout_s":300}
```

结果：`status=success`，输出 4,784 字符，结构为多文件 Cargo 工程
（`Vec3` 数学 → `ray`/`hit` 射线–球求交 → `BUY/LIVE/END` 回合状态机 → 队伍计分）。

关键词对照: `weapon`=11、`ray`=5、`buy`=2、`live`=6、`struct`=6、`enum`=1、
**`tetris`=0、`俄罗斯方块`=0**。

**结论**: LLM 侧完全能产出领域正确的 CS 代码；缺失发生在
`core/native_executor` 的 Planner/Writer —— 它们被硬编码为俄罗斯方块。
（与静态审计发现 AUD-11 一致。）

但仍不达标：该路径只返回文本，**不落盘、不构建、不跑测试、不打包**，无法形成可运行交付物。

---

## 6. 四项系统性缺陷（本次运行实测）

### V-01 🔴 内核领域硬编码，任务导入链路无泛化能力
`core/native_executor/`（3,006 行）内置 `RULE_BASED_TETRIS_PLAN`、
`build_tetris_payload_map()` 与 `tetris_original_prompt.py`。`Planner.plan()` 在
LLM 规划失败时**无条件 fallback 到 7 步俄罗斯方块计划**：

```python
# native_executor/planner.py:168-174
llm_result = self._try_llm_plan(...)
if self._is_valid_step_list(llm_result):
    return llm_result
return copy.deepcopy(RULE_BASED_TETRIS_PLAN)   # ← 与任务无关的固定计划
```

Writer 随后按该计划写入 `js/tetris.js` 等固定文件。任何非俄罗斯方块任务都会被
"成功"地产出俄罗斯方块。

### V-02 🔴 子任务未执行却报父任务完成
8 个 REQ 子任务全部 `pending / 0%`，父任务 `completed / 100% / step=done`。
`_execute_task_background_v2` 只推进父任务的四阶段，从不派发子任务。

### V-03 🔴 验证失败被谎报为成功
`validation_pass=False`、`warnings=["Validator failed 1/2 commands"]`，
但 `status=completed`、`progress=100`、`deliverable_blocked=false`，
溯源审计的 `warnings` 字段甚至是 **空数组**。对照工程准则 №12「失败要大声暴露」，
当前实现把失败包装成成功。

### V-04 🟠 归档体积填充文件（虚增交付物）
交付包内含 2,157,850 字节的 `ARCHIVE_VOLUME_PADDING.txt`，其自述为：

```text
# ARCHIVE VOLUME PADDING — 归档体积完整性填充
# 本文件为交付归档的体积达标填充文件，保证 .tar.gz / .zip 两份压缩包在任何
# gzip/deflate 压缩级别下均达到 ≥ 200KB 的最低交付阈值。
```

即：为了让归档"看起来够大"，系统主动注入无功能价值的填充内容。
这直接损害交付物可信度，且该文件被写入 `manifest.json` 作为正式交付项。

---

## 7. 验收评定（对照导入文档的验收标准）

| 验收标准 | 结果 | 说明 |
|----------|:----:|------|
| Rust 服务端可编译（cargo build --release） | ⚠️ | 能编译，但编的是俄罗斯方块 |
| 核心逻辑单元测试通过（cargo test） | ⚠️ | 34 个测试通过，但测的是俄罗斯方块 |
| 前端可构建（npm run build 或等价） | ❌ | 未提供前端构建工程，仅静态 HTML/JS |
| ≥2 名玩家同房对战 | ❌ | 无网络层、无服务端、无多客户端 |
| 命中判定服务端权威 | ❌ | 无射击/命中概念 |
| README + 一键构建启动脚本 | ⚠️ | 有 README，但描述俄罗斯方块 |
| ≥3 轮迭代记录 | ❌ | 有 4 次内部迭代，但无对用户可见的迭代记录 |
| ≥1 项性能优化量化对比 | ❌ | 无 |
| CS 风格回合制（购买/计分/胜负） | ❌ | 无 |
| REQ-001…REQ-008 逐条落实 | ❌ | 8 个子任务全部 pending |

**综合得分**: 交付物与需求匹配度 **0/8 REQ**；流程完整性 ⚠️ 部分达成；可信度 ❌ 失败被隐藏。

---

## 8. 根因与修复 Roadmap

### 根因
1. `native_executor` 是"为俄罗斯方块演示写的专用模板生成器"，被当作通用自主开发内核使用。
2. ITD 导入产出的父子任务图没有执行调度器（导入即建 8 子任务，但无人消费）。
3. 任务终态判定只看流程是否走完，不看验收标准是否满足（`validation_pass` 未参与终态）。
4. 交付层为满足体积阈值注入填充文件。

### 修复 Roadmap

**P0（可信性，必须最先修）**
1. 终态与验收挂钩：`validation_pass=False` 时父任务必须为 `failed/partial`，
   `deliverable_blocked=true`，并把 validator 失败原因写入溯源 `warnings`。
2. 移除 `ARCHIVE_VOLUME_PADDING.txt` 及一切体积填充逻辑；交付体积不做下限要求。
3. 子任务调度器：父任务 execute 时按 REQ 拓扑派发子任务并汇总，未完成则父任务不得 completed。

**P1（泛化能力，让内核不再只会俄罗斯方块）**
4. 拆分 `native_executor`：领域内容（俄罗斯方块模板）整体下沉到 `plugins/`；
   内核只保留「LLM 规划 → 白名单写盘 → 构建/测试 → 修复回环 → 打包」骨架。
5. 新增通用 Writer：由 LLM 输出 JSON 文件清单（path→content），复用现有
   `Writer._assert_safe_path` 白名单校验后落盘（该白名单机制已实现且可用）。
6. 通用修复回环：把 `cargo build/test`、`npm run build` 的失败输出回灌给 LLM，
   驱动多轮"实现→验证→修复"，并把每轮结论写入交付文档（满足 REQ-006）。

**P2（质量与合规）**
7. 性能基线采集与前后对比（REQ-007）。
8. 迭代记录、需求覆盖矩阵（REQ-001..008 ↔ 产物路径）自动生成。
9. ITD 解析器的 `模式A/B` 标签不应作为 warning 上报（当前误报，见 §9）。

---

## 9. 附带发现

| ID | 问题 | 证据 |
|----|------|------|
| V-05 | ITD 解析把模式标签当警告上报 | `/tasks/itd/parse` 对合法 Mode A 文档返回 `warnings:["模式A/B"]`，并给出"建议使用标准模式A格式"的错误建议（该标签来自 `_detect_mode()` 的返回值，非真实告警） |
| V-06 | 交付目录未持久化 | `run_task_*` 工作目录在执行后消失，仅保留 tar/zip；无法复核中间产物（`TEST_REPORT.md` 仍引用已不存在的路径） |
| V-07 | 内存峰值采集异常 | `TEST_REPORT.md` 记录 `内存峰值: 2210922496.0 MB`，明显单位错误 |

---

## 10. 结论

本次验证严格按照"不越俎代庖"原则执行：**全程由 MoRE OS 自身的 ITD 导入与执行链路作业**，
人工未代写任何一行游戏代码。

结论是明确的不达标，且问题性质严重：

- 系统能把任务**跑完并打包**（流程外壳可用）；
- 但内核**只会产出俄罗斯方块**，对 CS 射击游戏需求零响应（V-01）；
- 8 条需求子任务**从未执行**（V-02）；
- 验证失败被**包装成 completed/100%**（V-03）；
- 交付物靠**2.1 MB 填充文件**虚增体量（V-04）。

对照第 3 步已完成的 API Key 全流程治理（18 项端到端验证全过、全量测试 1133/0），
可以得出一个清晰判断：**MoRE OS 的"平台治理层"相对成熟，而"自主开发内核层"尚未达到
可交付真实软件产品的水平。** 若要满足「长周期自主开发 + 多轮迭代 + 一次性交付成熟成果」，
必须先完成 §8 的 P0 与 P1 修复，再重跑本验证。


---

## 11. 缺陷修复与复验（P0 已完成）

针对本次验证暴露的**可信性缺陷**（不涉及游戏能力本身），已完成修复并复验。

### FIX-1 验证失败不再谎报成功（对应 V-03）✅

`more_core/more_core/api/routers/tasks.py::_execute_task_background_v2` 的终态由
`validation_pass` 决定：

```python
verified_ok  = validation_pass is True
final_status = "completed" if verified_ok else "failed"
final_progress = 100 if verified_ok else 90
...
"current_step": "done" if verified_ok else "validation_failed",
"error": None if verified_ok else "validation did not pass",
```

复验（同一 ITD 文档重新导入执行）:

| 项目 | 修复前 | 修复后 |
|------|--------|--------|
| status | `completed` | **`failed`** |
| progress | `100` | **`90`** |
| current_step | `done` | **`validation_failed`** |
| error | `null` | **`validation did not pass`** |
| warnings | `["Validator failed 1/2 commands"]` | 追加 **"…deliverables are NOT verified"** |

### FIX-2 溯源审计阻断未验证交付物（对应 V-03）✅

`core/guardrails/provenance_audit.py::audit()` 新增规则：最终记录
`validation_pass=False` 或 `final_status=failed` 时强制
`deliverable_blocked=True`。

```json
{"deliverable_blocked": true,
 "execution_channel": "native_planner_loop",
 "files_written_count": 13,
 "total_iterations": 4,
 "warnings": ["deliverable blocked: validation_pass=False on the final record",
              "deliverable blocked: final_status=failed"]}
```

### FIX-3 移除归档体积填充文件（对应 V-04）✅

`core/native_executor/delivery.py` 不再写入 `ARCHIVE_VOLUME_PADDING.txt`。

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 交付包内填充文件 | `ARCHIVE_VOLUME_PADDING.txt` 2,157,850 B | 无 |
| zip 体积 | 318 KB | **40 KB** |
| tar.gz 体积 | 289 KB | **35 KB** |

### FIX-4 回归护栏 ✅

更新 `tests/test_provenance_audit.py::test_v2_executor_updates_task_store_fields`：
原先断言"验证失败也必须 completed"（正是把缺陷固化为契约），现改为
**终态必须与 validator 结果一致**，并断言未通过验证时
`deliverable_blocked is True`。

复验结果：`pytest tests/ → 1133 passed, 0 failed`。

### 仍未修复（需要产品级改造）

| ID | 缺陷 | 状态 |
|----|------|------|
| V-01 | `native_executor` 领域硬编码为俄罗斯方块，无泛化能力 | ⏳ 待做（§8 P1） |
| V-02 | 8 个 REQ 子任务从无调度器，全部 pending 而父任务照常推进 | ⏳ 待做（§8 P0-3） |
| V-05 | ITD 模式标签被当作 warning 上报 | ⏳ 待做 |
| V-06 | 执行工作目录在 finally 中被删除，中间产物不可复核 | ⏳ 待做 |
| V-07 | 内存峰值单位错误（报告 2210922496.0 MB） | ⏳ 待做 |

> 修复 V-03/V-04 之后，系统**不再把失败包装成成功**：当前对同一 CS 任务会如实返回
> `failed` 并阻断交付。这意味着后续任何"MoRE OS 达标"的结论都必须建立在真实通过验证
> 的交付物之上，而不是流程走完即可。

---

*验证人: Codex · 2026-09-29 · 全程经 MoRE OS API 驱动，未人工代写游戏代码*
