# BaiLongma 能力融合 v0.2：监察调查报告 + 深化规划大纲

> 状态：草案，供评审
> 日期：2026-08-14
> 前置文档：`BAILONGMA_CAPABILITY_FUSION_DRAFT.md`（v0.1）
> 新增输入：`rust-bailongma-MAC`（BaiLongma Rust 版，413 测试全绿、5 轮安全审计）
> 方法：先对 v0.1 做批判性审查（Part A），再给出修订大纲（Part B）

---

# Part A · 监察调查报告（对 v0.1 草案的审查发现）

## F1【严重 · 战略误判】重写策略在 Rust 版面前不成立

v0.1 §1.2 主张"BaiLongma 是 Node.js，能力原语用 Python 逐模块重写，sidecar 仅作过渡"。
**事实更正**：`rust-bailongma-MAC` 已是完整 Rust 原生实现——

- 意识循环全链路接线（inbound → 归属/注入/落库 → LLM 工具循环 → 回复广播），
  见 `crates/core/src/runtime.rs`（对齐 Node `runTurn` 756-845）
- 四层幂等已落地：工具台账 `UNIQUE(request_id, round, attempt, tool_name)`、
  LLM 重试 `Idempotency-Key`、`DbToolReplayGuard` 防重放、round_limit 终态
- 沙箱子进程（JSON-RPC、能力令牌、参数脱敏）经 5 轮安全审计
  （路径穿越、白名单绕过、LAN 裸读等高危项已修复并回归锁定）
- 413 测试全绿，逐轮递增有基线（M1 351 → 第 5 轮审计 413）

**结论**：Python 重写将丢弃全部已验证资产并重踩已修复的坑。v0.2 改为**复用优先**。

## F2【严重 · 关键机制遗漏】v0.1 漏掉了四块已验证资产

1. **唤醒闭环**（`wakeup.rs`）：N 条到期提醒合并 1 次唤醒 + 周窗口预算闸门。
   v0.1 的三个 cron job 只回答了"醒来做什么"，没有回答"何时醒、这一醒值不值"——
   而这恰是"自组织"的治理难点（唤醒风暴实证：8→1 合并有测试）。
2. **人工介入硬通道**（`approval.rs` / `intervention.rs`）：Rust 版评审 E6 裁决——
   "任何自动动作可一键回滚，不能晚于自动行为"。v0.1 对 P0-P3 全部自动 job
   （consolidation/recognizer/review）均未设一键禁用与回滚路径。
3. **重放与追踪**（`llm/replay.rs`、`trace.rs`）：v0.1 的幂等是"规范级"
   （约定 dedupe key，靠开发者自觉）；Rust 版是"台账级"（DB UNIQUE 强制 + 重放守卫）。
   规范级在并发下必漏。
4. **观测基座**（`llm/metrics.rs` 四表 + `llm_context_sections` 命中统计）：
   v0.1 §6 定了召回命中率等五个指标，但全方案没有测量基础设施——
   不埋点，指标永远停留在纸面。E2 立场：埋点先行，接线当天出第一份数据。

## F3【中等 · 架构判断错误】三处需纠正

1. **注入钩子位置**：v0.1 主张 MemoryInjector 进 `Layer.run()` 基类
   （`layers/base.py`）。这违反 G2"分层可替换"——基类改动强加于所有层实现
   （含第三方插件层）。正确做法：middleware 模式，挂在 `MoRECore` 编排侧
   （`runtime/orchestrator.py` 已是组合点），层自身无感。
2. **召回公式饿死老记忆**：v0.1 的连乘式 `sim × importance × exp(−decay·t) × log(1+n)`
   在 embedding 为 NULL 时（backfill 未完成 / Embedder 未配置）sim=0，全条目归零。
   Rust 版把注入与检索分离（`injector.rs` / `retrieval.rs`），
   缺向量时降级走关键词 + 时间衰减路径。v0.2 采纳该模式。
3. **insight 可见性自相矛盾**：v0.1 §7.3 说"insight 默认仅同命名空间可见"，
   §4 却让 L4 负责"跨域关联"——跨域灵感的价值正在于跨命名空间碰撞。
   v0.2 改为三级可见性：私有 / 域内 / 全局广播，全局级需过治理闸门 + Taint 标签传播。

## F4【中等 · 工程缺口】

- v0.1 P0"冻结接口"未列出冻结哪些 Protocol 签名；v1→v2 老库迁移无验证路径
  （Rust 版经验：加列必须走幂等迁移 `table_info` 补列，其评审 E6 质询过此坑）。
- 无 feature flag 管理机制（命名、默认值、清理责任人）。
- 无双运行时故障降级设计：Rust 底盘不可用时 qnm-os 行为未定义。
  Rust 版自身答案是"降级回复、不空转不崩溃"，qnm-os 侧需同等语义。

## F5【轻微】向量规模假设过松

v0.1 "<10k 条目纯 Python 余弦够用"未计入多 Agent 放大：hands × council 角色 ×
长会话线程，条目放大 1-2 个数量级；且注入路径对 P50 延迟敏感，纯 Python 余弦不可行。
v0.2：检索下沉 Rust 侧（rusqlite 本地 + 预留 sqlite-vec），Python 侧零计算。

---

# Part B · 深化规划大纲 v0.2

## B0. 核心架构决策：双运行时"底盘-大脑"模型

替代 v0.1 的"Python 重写"：

```text
┌─────────────────────────────────────────────────────────┐
│ qnm-os (Python) — 分层治理大脑                           │
│   L0-L5 层、council 评审团、governance、进化裁决          │
│   新增：MemoryFacet 客户端、注入 middleware、唤醒预算闸门  │
└──────────────┬──────────────────────────────────────────┘
               │ A2A 协议为主干（事件 + 任务委托）
               │ JSON-RPC 为辅（沙箱协议复用）
┌──────────────▼──────────────────────────────────────────┐
│ BaiLongma Rust — 功能性底盘基座（Chassis Runtime）        │
│   意识循环 · 记忆注入 · 工具循环 · 四层幂等台账            │
│   沙箱 · LLM 指标四表 · 唤醒闭环 · 蒸馏冷启动             │
│   （413 测试、5 轮审计资产直接复用，不重写）               │
└─────────────────────────────────────────────────────────┘
```

分工一句话：**Rust 底盘管"记得住、跑得稳、可重放"，qnm-os 大脑管"分得层、评得审、治得住"。**

为什么 A2A 为主干而非 sidecar 库调用：
- qnm-os 已有 `a2a/client.py` 与 agent-card 机制；BaiLongma Rust 已有 axum server，
  挂 `/a2a` 适配端点成本远低于 PyO3 嵌入（后者耦合构建链、调试跨语言栈）
- 两运行时各自独立部署、独立崩溃域；故障降级语义清晰
- sidecar 双进程形态保留为开发模式（单机上 `cargo run` + `make start`）

## B1. 五大增强域（修订版）

### D1 长程记忆体——权威在 Rust，Python 持投影

- 记忆 schema 以 Rust 侧 SQLite 为权威；qnm-os 侧 `MemoryStore` 降级为
  **任务级缓存 + 投影**，不再另建长程存储（避免双写不一致）。
- 新增 `MemoryFacet` 客户端（Python）：`recall(focus, budget)` / `commit(entry)` /
  `subscribe_insight(handler)`，经 A2A 调 Rust 记忆面。
- 跨运行时归属：qnm-os 写入的记忆带 `source_layer` / `source_agent` 标签，
  对接 Rust 侧已有的写时归属印章机制（`RuntimeState.focus_topic` / `current_thread_id`）。
- 长期记忆回顾：复用 Rust `threads.rs`（话题线程）+ 巩固循环；
  qnm-os L4/L5 通过 `subscribe_insight` 接收回顾产物，不重复造 consolidator。

### D2 自组织——唤醒治理 + 人工闸门前置

- **唤醒预算闸门**移植：qnm-os `cron/manager.py` 增加 budget gate——
  每个 job 注册唤醒成本与收益声明，周窗口预算超限则合并/推迟（对齐 wakeup.rs 模式）。
- **人工介入硬通道进 P0**（E6 裁决本地化）：
  任何自动 job 一键禁用（config + API）、任何自动写入可一键回滚
  （qnm-os 已有 `DeliverableContract` + `KillCriterion`，扩展为 job 级 kill switch）。
- 治理循环：council 定期评审系统自身 job 配置（元认知自组织），
  产出调整建议走 approval，不自动生效。

### D3 深度神经网络 / 深度学习——对齐"只蒸馏确定性子问题"裁决

采用 Rust 版 `evolution/distill.rs` 已锁定的路径（E4 立场，qnm-os 侧同构执行）：

1. **语料零成本积累**：qnm-os 审计日志与任务记录预留 `label` 列（schema 现在就留位，
   别到 P4 才发现语料没有标注位）。
2. **规则标注冷启动**：importance 打分、意图分类、敏感检测先规则实现，
   规则输出即 ground truth，单测 100% 复现锁定，防标注漂移。
3. **小模型试点**（P3）：ONNX 本地推理，只接确定性子问题；不做端到端训练。
4. **LoRA / 端到端微调**：默认关闭，走 L2 受控进化管道（沙箱 + 审计 + 人类 veto）。

### D4 灵感触发——机制不变，实现重定位

- 定义维持 v0.1：**离线联想 + 在线召回**。
- 实现位置修正：Recognizer 放 Rust 侧（近记忆数据，复用 `self_evolution.rs` /
  `capability_demo_intent.rs` 意图触发先例）→ insight 经 A2A 事件推送 qnm-os →
  qnm-os 注入 middleware 在编排层按 FocusFrame 召回（**不进 Layer 基类**，纠正 F3.1）。
- 可见性三级：私有（source_agent）/ 域内（同 tenant）/ 全局广播；
  全局级须过 PolicyEnforcer + Taint 标签传播，初期全局级默认关闭。
- 噪声治理：insight 产生速率限流 + 召回排序保守起步 + 人工标注反馈回路
  （标注数据回流 D3 语料）。

### D5 幂等策略——从规范级升级到台账级

qnm-os 侧补齐 Rust 版四层幂等的同构物：

| 层 | Rust 版机制（参照） | qnm-os 侧落地 |
|---|---|---|
| 请求 | `Idempotency-Key` + 结果缓存 | `POST /api/v1/tasks/execute` 同头部，重复返回缓存结果 |
| 工具 | 台账 `UNIQUE(request_id, round, attempt, tool)` | tools 执行台账表，同构唯一约束 |
| 重放 | `DbToolReplayGuard` | 任务重放守卫：同 task_id 副作用工具不重复执行 |
| 终态 | round_limit 终态机 | 任务状态机终态收敛（对齐 E1 裁决：定义终态覆盖语义，失败态先到/成功态后到的翻转不吞状态） |

后台 job 维持 v0.1 设计：`(job_name, window_key)` dedupe + checkpoint 增量 + 崩溃续跑。

## B2. 修订路线图

| 阶段 | 周期 | 内容 | 出口标准（可测量） |
|---|---|---|---|
| **P0 链路·观测·闸门** | 1-2 周 | A2A 桥接通（ping/echo/任务委托最小链路）；双端埋点（qnm-os 侧建 llm 调用表 + 注入命中表，同构 Rust 四表）；job kill switch + 回滚机制；feature flag 登记册 | 桥接链路 e2e 绿；埋点表有真实行；kill switch 演练通过 |
| **P1 记忆面打通** | 2-3 周 | MemoryFacet 客户端 + 注入 middleware（编排侧）；召回降级路径（无向量走关键词+衰减）；双库迁移幂等脚本 | 注入 P50 < 50ms；缺向量场景召回不为空；迁移脚本重复跑状态一致 |
| **P2 自组织治理** | 2-3 周 | cron budget gate；唤醒合并；council 自评审循环（建议走 approval） | 唤醒风暴测试（N→1）；预算超限有拦截记录；评审建议零自动生效 |
| **P3 学习冷启动** | 2 周 | 审计日志 label 列；规则标注器 + 锁定单测；ONNX 小模型试点（importance 打分） | 规则标注 100% 复现；试点模型离线指标 ≥ 规则基线才允许上线 |
| **P4 灵感与进化深化** | 持续 | insight 三级可见性放开评审；LoRA 管道 ADR；双运行时混沌演练 | 灵感有效召回率人工抽检 ≥ 60%；LoRA 演练全程有 veto 记录 |

与 v0.1 的关键差异：P0 从"冻结接口"改为"**链路 + 观测 + 闸门**"——
先让两个运行时说话、让数据开始流动、让逃生口就位，再谈增强。

## B3. 验证指标体系（含测量方式）

| 指标 | 测量 | 目标 |
|---|---|---|
| 记忆召回命中率 | 注入命中表 + LLM 输出引用检测 | ≥ 40% |
| 注入延迟 | middleware 计时（P50/P99） | P50 < 50ms |
| 幂等正确性 | 同窗口重复跑 N 次 DB 状态 diff | 零 diff |
| 唤醒经济性 | 唤醒次数 / 有效动作比、预算消耗曲线 | 风暴场景 N→1 |
| 灵感有效率 | 人工抽检标注（回流 D3 语料） | ≥ 60%，噪声率 < 20% |
| 跨运行时可用性 | Rust 底盘宕机时 qnm-os 降级行为 | 降级响应，不空转不崩溃 |

## B4. 风险登记册

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 双运行时运维复杂度翻倍 | 开发模式 sidecar 一键起；`scripts/health_check.sh` 扩展为双端互查 |
| R2 | A2A 桥成为单点 | 桥降级为直连 HTTP 适配器；桥本身无状态可重启 |
| R3 | 双库（Rust SQLite × qnm-os data/）一致性 | 权威-投影单向流动，禁止反向写；备份策略各自独立 |
| R4 | insight 全局广播的信息泄露面 | 全局级默认关；Taint 标签随事件传播；开广播需 ADR |
| R5 | 跨语言调试成本 | trace_id 贯穿 A2A 调用链，双端日志可拼接 |
| R6 | Rust 侧演进不受 qnm-os 控制 | 桥接协议版本化（v1 冻结）；契约测试进双端 CI |
| R7 | 小模型试点的分布偏移（评审 E2 质询过：对话语料 ≠ 任务语料） | 试点仅限 importance 打分（数据同源）；意图分类等跨域任务另立项 |
| R8 | 特征蔓延：六层全接导致每阶段不可验收 | 每阶段出口标准绑定单一可测指标；未达标不进入下阶段 |

## B5. 开放问题（需拍板）

1. **部署形态**：生产推荐 A2A 独立双服务，开发模式 sidecar——是否接受双进程为常态？
2. **记忆权威**：Rust 侧 SQLite 为唯一权威后，qnm-os 现有 `memory/sqlite_store.py`
   降为任务级缓存——是否接受该模块最终退役？
3. **insight 全局广播**：P4 之前默认关闭，开放时走 ADR + PolicyEnforcer——门槛是否足够？
4. **council 自评审的产出**：仅建议（走人工 approval）还是允许低风险项自动生效？
   草案立场：仅建议，零自动生效。

---

*本文档由 v0.1 草案经监察审查后修订，审查发现 F1-F5 均已在大纲中闭环。*
*下一步：B5 四题拍板后，拆 ADR（桥接协议 v1 / 记忆权威迁移 / 幂等台账 / 蒸馏冷启动）。*
