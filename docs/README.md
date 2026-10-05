# QNMing MoRE OS — 文档中心

> 最后整理：2026-10-04。目录约定：**顶层只放"仍在用的规范/手册"**，
> 审计、验证、评估、回溯等**过程性材料统一进 `audits/`**，设计稿进 `design/`。

---

## 1. 规范与手册（顶层）

| 文档 | 说明 |
|------|------|
| [INSTALL.md](INSTALL.md) | 安装与环境准备 |
| [OPERATION_MANUAL.md](OPERATION_MANUAL.md) | 日常运维手册 |
| [ARCHITECT_RULES.md](ARCHITECT_RULES.md) | 架构与编码约束 |
| [API_KEY.md](API_KEY.md) | API Key 格式、配置与故障排查 |
| [API_KEY_LIFECYCLE.md](API_KEY_LIFECYCLE.md) | API Key 全生命周期：生成/存储/分派/用量/轮换 |
| [CODEGEN_LOOP_SPEC.md](CODEGEN_LOOP_SPEC.md) | 代码生成 Agentic Loop 规范 |
| [ENHANCEMENT_PLAN.md](ENHANCEMENT_PLAN.md) | 增强路线图与待办 |
| [import-task-spec.md](import-task-spec.md) / [.pdf](import-task-spec.pdf) | ITD 任务导入文档规范 |
| [adr/](adr/) | 架构决策记录（ADR） |

## 2. 审计与评估（`audits/`）

### 2.1 综合审计

| 报告 | 说明 |
|------|------|
| [AUDIT_REPORT_2026-09-29.md](audits/AUDIT_REPORT_2026-09-29.md) | v0.9.9 综合代码审计（18 项发现） |
| [AUDIT_REPORT_2026-08-04-followup.md](audits/AUDIT_REPORT_2026-08-04-followup.md) | 2026-08-04 修复后复审计（当时全绿基线） |
| [AUDIT_REPORT_2026-08-04.md](audits/AUDIT_REPORT_2026-08-04.md) / [2026-07-07](audits/AUDIT_REPORT_2026-07-07.md) | 更早历史审计 |

### 2.2 专项审计与评估

| 报告 | 说明 |
|------|------|
| [LAYER_TEST_MATRIX_2026-10-05.md](audits/LAYER_TEST_MATRIX_2026-10-05.md) | L0–L5 分层综合测试矩阵 + CI 门禁（含故障隔离负向验证） |
| [GOVERNANCE_OBSERVABILITY_2026-10-05.md](audits/GOVERNANCE_OBSERVABILITY_2026-10-05.md) | 治理拦截率 + 阈值告警 + Prometheus 导出 |
| [COUNCIL_REVIEW_BASELINE_2026-10-05.md](audits/COUNCIL_REVIEW_BASELINE_2026-10-05.md) | L4→L5 Council 复评量化基线 + 看板接入 |
| [PROVIDER_HEALTH_OBSERVABILITY_2026-10-05.md](audits/PROVIDER_HEALTH_OBSERVABILITY_2026-10-05.md) | LLM provider 预检落库 + 无效模型标识告警 |
| [OBSERVABILITY_INTEGRATION_2026-10-05.md](audits/OBSERVABILITY_INTEGRATION_2026-10-05.md) | 运行健康总览（五类指标整合 + 统一裁决） |
| [RCA_AND_FIX_2026-10-04.md](audits/RCA_AND_FIX_2026-10-04.md) | 三大硬伤（产出正确性/交付可信度/可观测性）根因分析 |
| [STAGE_EVALUATION_2026-10-04.md](audits/STAGE_EVALUATION_2026-10-04.md) | 阶段成果评估（需求逐条对照 + 达成度评分） |
| [HARDENING_BATCH_2026-10-04.md](audits/HARDENING_BATCH_2026-10-04.md) | 加固批次 1–4（R-01…R-19 / D-1…D-4 / 生产效率） |
| [RESIDUAL_RISKS_2026-10-04.md](audits/RESIDUAL_RISKS_2026-10-04.md) | 残留风险清单（含修复状态） |
| [CODEGEN_CHAIN_PERFORMANCE_AUDIT_2026-10-04.md](audits/CODEGEN_CHAIN_PERFORMANCE_AUDIT_2026-10-04.md) | 代码生成链路性能审计 |
| [CS_SHOOTER_TASK_VERIFICATION.md](audits/CS_SHOOTER_TASK_VERIFICATION.md) | CS 射击游戏任务端到端验证（含不达标结论） |
| [BAILONGMA_FUSION_V2_AUDIT_AND_OUTLINE.md](audits/BAILONGMA_FUSION_V2_AUDIT_AND_OUTLINE.md) | 白龙马融合 v2 审计与纲要 |
| [RELEASE_NOTE_P1_5_PERMANENT_GUARDRAILS.md](audits/RELEASE_NOTE_P1_5_PERMANENT_GUARDRAILS.md) | P1.5 永久护栏发布说明 |
| [STEP_5_SUMMARY_REPORT_2026-09-26.md](audits/STEP_5_SUMMARY_REPORT_2026-09-26.md) | Step-5 阶段总结 |

### 2.3 回溯分析（`audits/retrospective/`）

| 文件 | 说明 |
|------|------|
| [RETROSPECTIVE_REPORT.md](audits/retrospective/RETROSPECTIVE_REPORT.md) | 越权代执行偏差整改报告 |
| [retrospective_tasks_table.csv](audits/retrospective/retrospective_tasks_table.csv) | 41 项任务回溯明细 |
| [retrospective_summary.json](audits/retrospective/retrospective_summary.json) | 聚合统计 |
| [verify_retrospective.py](audits/retrospective/verify_retrospective.py) | 回溯数据断言脚本 |

## 3. 设计稿（`design/`）

| 文档 | 说明 |
|------|------|
| [BAILONGMA_CAPABILITY_FUSION_DRAFT.md](design/BAILONGMA_CAPABILITY_FUSION_DRAFT.md) | 白龙马能力融合设计草案 |

## 4. 运行记录与图示

| 目录 | 说明 |
|------|------|
| [CODEGEN_RUNS/](CODEGEN_RUNS/) | 代码生成迭代运行记录 |
| [images/](images/) | 架构图、演进路线图、性能基准对比 |

## 5. 内核架构白皮书

见 [more_core/ARCHITECTURE.md](../more_core/ARCHITECTURE.md)。

---

## 维护约定

1. **新增过程性材料**（审计/评估/验证/回溯）一律放 `audits/`，命名 `<类型>_<日期>.md`。
2. **顶层只保留"当前仍生效"的规范与手册**；过期文档不删除，移入 `audits/` 留档。
3. **测试产物不入库**：`MagicMock/`、`*.bak.*`、构建产物 `target/`、根目录压缩包已在 `.gitignore` 中屏蔽。
