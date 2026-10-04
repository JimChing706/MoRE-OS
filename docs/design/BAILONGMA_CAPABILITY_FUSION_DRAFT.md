# BaiLongma 能力融合与全层 Agent 增强方案（草案 v0.1）

> 状态：初步构想草案，供评审
> 日期：2026-08-13
> 范围：more_core 内核、layers、cron、hands、council、A2A

---

## 1. 背景与目标

### 1.1 现状盘点

**qnm-os (MoRE OS)**：六层架构（L0 执行 / L1 编排 / L2 进化 / L3 符号 / L4 认知 / L5 元认知），
治理完备（RBAC、Taint、Audit、PolicyEnforcer），但基础 Agent 能力单薄：

- 记忆系统仅三流（episodic/semantic/procedural）+ bounded deque + SQLite KV；
  无向量语义检索、无遗忘衰减、无巩固循环、无上下文注入中间件。
- `LayerContext.scratch` 只有任务级生命周期，跨任务、跨会话的长程状态无处安放。
- `cron/` 已存在但后台认知循环（巩固/回顾/模式识别）尚未挂上。

**BaiLongma**：单 Agent 个人助手（Node.js），但感知-记忆-注意力-回顾闭环成熟，
`src/memory/` 下 17 个子模块经过实战迭代：

- 遗忘曲线（importance + decay_rate + last_accessed_at）
- embedding 语义检索与回填（embedding-backfill）
- 记忆巩固（consolidator / consolidation-loop）
- 注意力焦点（focus / focus-classifier / focus-compress）
- 上下文注入（injector / injector-retrieval / injector-format）
- 模式识别（recognizer / recognizer-scheduler）——"灵感触发"的雏形
- 复盘（review/reviewer）、预取（prefetch）、自我感知（self-perception）
- 话题线程（threads / thread-summarize）、时间解析（temporal-parser）
- 环境感知（desktop-scanner / installed-software-scanner）

### 1.2 目标

把 BaiLongma 验证过的单 Agent 能力**打碎、抽象、下沉**为 qnm-os 的层间公共能力，
使 L0–L5 各层、hands/council/A2A 各类 Agent 按需取用，而非在 qnm-os 里复制一个 BaiLongma。

核心原则：**不是移植，是提取能力原语，按层装配。**

技术栈说明：BaiLongma 是 Node.js，qnm-os 内核是 Python。
建议将能力原语用 Python 重写进 `more_core`，BaiLongma 作为参照实现与测试语料来源；
过渡期内可选 sidecar 模式（HTTP 调用 BaiLongma API），但不做长期依赖。

---

## 2. 能力映射表（BaiLongma 模块 → qnm-os 装配点）

| BaiLongma 模块 | 能力原语 | qnm-os 落点 | 受益层 |
|---|---|---|---|
| memory (importance/decay) | 遗忘曲线记忆 | `memory/store.py` MemoryEntry v2 | 全层 |
| embedding.js, embedding-backfill | 语义向量检索 | 新增 `memory/embedding.py`（Provider 中立） | L0/L1/L4 |
| consolidator, consolidation-loop | 记忆巩固 | 新增 `memory/consolidation.py` + cron job | 系统级 |
| focus, focus-classifier, focus-compress | 注意力焦点帧 | 新增 `planning/focus.py`，注入 LayerContext | L1 主导 |
| injector 三件套 | 上下文注入中间件 | 新增 `memory/injector.py`，Layer 前置钩子 | L0/L4 |
| recognizer + scheduler | 模式识别 → 灵感触发 | 新增 `metacognition/recognizer.py` + cron | L4/L5 |
| review/reviewer | 任务复盘 | cron ReviewJob，输出喂 L2 进化 | L5/L2 |
| refresh-loop | 记忆刷新强化 | 并入 ConsolidationJob | 系统级 |
| self-perception | 自我感知指标 | 喂 `metacognition/calibrator.py` | L5 |
| threads, thread-summarize | 话题线程/摘要 | `channels/` 会话管理增强 | L1 |
| temporal-parser | 时间感知 | 工具化为 `tools/` | L0 |
| prefetch | 预测性资源预取 | `planning/` 内基于 FocusFrame | L1 |
| concept-extractor | 概念抽取 → 本体 | 接 `ontology/`（AOW 兼容） | L3 |
| voice (ASR/TTS) | 语音通道 | `channels/voice.py`（后置阶段） | 通道层 |
| desktop/software scanner | 环境感知 | 工具化 + RBAC 收紧 | L0 工具 |

---

## 3. 五大支柱设计

### 支柱 A：统一长程记忆体（MemoryEntry v2）

扩展现有 `MemoryEntry`，保持三流并新增第四流 `insight`（洞见/灵感）：

```python
@dataclass(slots=True)
class MemoryEntryV2:
    # 既有字段保留：id, kind, content, tags, score, created_at, access_count, task_id, layer, ttl
    importance: float = 0.5          # 重要度 0-1（写入时由打分器给出）
    decay_rate: float = 0.01         # 遗忘系数
    last_accessed_at: float = 0.0    # 最近访问（召回时刷新）
    embedding: list[float] | None = None
    content_hash: str = ""           # 写去重（幂等基石）
    source_agent: str = ""           # 产生者（RBAC 命名空间）
    consolidated: bool = False       # 巩固增量标记
```

召回打分（BaiLongma 遗忘曲线的 Python 化）：

```text
recall_score = semantic_sim(query, entry)            # 向量相似度
             * importance
             * exp(-decay_rate * days_since_access)  # 时间衰减
             * (1 + log1p(access_count))             # 访问强化
```

存储：SQLite 先行（纯 Python 余弦，<10k 条目足够）；接口预留 sqlite-vec / Qdrant 适配点。

### 支柱 B：注意力与注入（FocusFrame + MemoryInjector）

- `FocusFrame`：当前任务的焦点描述（话题、实体、意图、时间窗、token 预算）。
  由 L1 编排层计算与更新，挂在 `LayerContext` 上随任务流转。
- `MemoryInjector`：Layer 前置钩子（`Layer.run()` 内 `process()` 之前），
  按 FocusFrame 检索 top-k 记忆，格式化后注入该层 prompt；默认注入预算 ≤ 上下文 20%。
- 注入与召回全程写 AuditLogger（G5 兼容）。

### 支柱 C：后台认知循环（自组织 + 灵感触发）

挂在现有 `cron/` 上的三个常驻 job：

1. **ConsolidationJob（巩固）**：周期性将高频访问的 episodic 条目提炼为 semantic；
   压缩冗余、回填 embedding、刷新 importance。对应"长期记忆并回顾"。
2. **RecognizerJob（模式识别 / 灵感触发）**：扫描近期记忆，发现重复模式、
   未完成线索、跨域关联，产出 `insight` 流条目。**灵感不是随机产生，
   而是"离线联想 + 在线召回"**：Recognizer 离线写入 insight，
   Injector 在后续相关任务中按 FocusFrame 召回——灵感在"恰当时机"浮现。
3. **ReviewJob（复盘）**：对已完成任务链回顾，修正 importance 权重，
   产出复盘报告喂给 L2 进化层与 L5 calibrator。

### 支柱 D：学习回路（"深度学习"的务实落地）

qnm-os 是 LLM 编排系统而非训练框架，分三级递进，优先级 1 > 2 > 3：

1. **嵌入向量**（现成模型）：语义检索、聚类、去重的地基，Phase 1 即落地。
2. **小头网络**（sklearn / 小型分类器）：importance 打分、focus 分类、
   thread 分类先从 BaiLongma 的规则版移植，积累数据后换成学得的小模型。
   训练数据来源：系统自身的审计日志（治理系统天然产标注数据）。
3. **LoRA / 在线微调**：默认关闭，必须走 L2 受控进化管道
   （沙箱 + 审计 + 人类 veto，符合 G4 原则）。

### 支柱 E：幂等与可靠性基线

- **Job 幂等**：所有后台 job 以 `(job_name, window_key)` 为 dedupe key；
  同一窗口重复执行不产生重复效果。
- **增量检查点**：`last_consolidated_at`、embedding backfill checkpoint；
  崩溃后从检查点续跑，不重放已完成窗口。
- **写去重**：`content_hash` 唯一约束 + upsert 语义。
- **API 幂等**：`POST /api/v1/tasks/execute` 支持 `Idempotency-Key` 头，
  重复提交返回缓存结果。
- **可追溯**：ReasoningStep 已有 id，配合审计日志支持任务重放。

---

## 4. 分层装配总览

| 层 | 获得的能力 | 调用方式 |
|---|---|---|
| L0 执行 | 记忆注入、temporal 工具、环境感知工具 | Injector 前置钩子 + tools |
| L1 编排 | FocusFrame 计算、thread 管理、prefetch | 编排器内建 |
| L2 进化 | 复盘数据流、LoRA 管道（受控） | ReviewJob 输出 |
| L3 符号 | 概念图谱（concept-extractor → ontology） | 语义记忆回流 |
| L4 认知 | insight 灵感召回、跨域关联 | Injector + insight 流 |
| L5 元认知 | self-perception 指标、记忆质量信号 | calibrator 输入 |

各类别 Agent（hands / council 成员 / A2A 对端）通过统一 `MemoryFacet` API 取用，
按 `source_agent` + RBAC 做命名空间隔离，Taint Tracking 扩展到记忆读写路径。

---

## 5. 实施路线

| 阶段 | 周期 | 内容 | 出口标准 |
|---|---|---|---|
| P0 冻结接口 | 1 周 | MemoryEntry v2 schema + 迁移脚本、幂等键规范、feature flag | 旧测试全绿 |
| P1 记忆体增强 | 2-3 周 | embedding + 衰减召回 + Injector 钩子，L0/L1 接入 | 召回命中率基线 |
| P2 后台循环 | 2-3 周 | 三个 cron job + insight 流 + 灵感召回 | 幂等性测试通过 |
| P3 注意力 | 2 周 | FocusFrame + importance 小模型试点 | 注入 token 占比下降 |
| P4 深化 | 持续 | LoRA 管道、voice 通道、环境感知工具化 | 按 ADR 逐个评审 |

## 6. 验证指标

- 记忆召回命中率：注入记忆被 LLM 输出实际引用的比例（目标 ≥ 40%）
- 跨会话长任务续接成功率
- 灵感有效召回率（人工标注抽样，噪声率 < 20%）
- 幂等性：同一 job 窗口跑 N 次，数据库状态一致
- 性能：注入延迟 < 50ms，记忆写入 < 5ms

## 7. 风险与开放问题

1. **JS → Python 重写工作量**：以 BaiLongma 为参照实现逐模块重写，
   用其测试语料做对照回归；sidecar 仅作过渡。
2. **向量检索规模**：<10k 纯 Python 余弦够用；规模大再切 sqlite-vec/Qdrant（接口预留）。
3. **共享 vs 隔离的张力**：跨层记忆共享与 RBAC/租户隔离冲突，
   需要 Taint Tracking 扩展 + insight 流默认仅同命名空间可见。
4. **灵感噪声**：insight 产生速率需限流，召回排序权重保守起步。
5. **上下文预算竞争**：记忆注入与系统提示、工具结果争抢窗口，需全局预算管理器。
6. **深度神经网络的边界**：P3 之前不引入训练框架依赖，保持内核轻量。

## 8. 与治理原则的对齐

- G1 领域无关：记忆体在 core，领域知识走 Industry Pack
- G2 分层可替换：Injector / FocusFrame 均为 Protocol + 基线实现
- G3 Provider 中立：embedding 走现有 LLM fallback 链
- G4 受控自进化：LoRA 仅经 L2 管道
- G5 本体审计：记忆读写、灵感产生、复盘结论全量审计
- G6 插件稳定：MemoryFacet API 纳入 12 个月兼容承诺

---

*本草案为初步构想，待评审后拆分为 ADR 与实施 issue。*
