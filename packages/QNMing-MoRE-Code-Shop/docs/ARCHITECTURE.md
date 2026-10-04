# 架构：一条可验证的代码生成链路

```
                     ┌──────────────── 产出正确性 ────────────────┐
需求 ─▶ LLM 生成 ─▶  │ syntax_gate │ logic_gate │ requirement_gate │ ─▶ 闸门未过 ⇒ 拦截 + 审计
                     └──────────────────────────────────────────────┘
                                   │ 通过
                                   ▼
                          沙箱执行 + 断言验证
                          （AST 策略 / 路径白名单 / 环境净化）
                                   │
                     ┌─────────────┴──────────────┐
                     ▼                            ▼
              交付台账（可信度）              运行指标（可观测性）
     状态/权责/版本/工件哈希/裁决/阻断原因     token/延迟分位/阶段耗时
                     │                            │
                     └────────► delivery_stats / metrics ◄────────┘
```

## 三层保障的判定语义

| 层 | 判定 | 失败时 |
|----|------|--------|
| 闸门 | 语法可解析 + 非占位实现 + 需求符号覆盖 ≥ 阈值 | `blocked`，原因 `gate_*_failed` |
| 控制器 | 沙箱是否跑通 + 断言是否通过 + 评审结论 | `escalated`，带 `cause` 分类 |
| 交付策略 | 闸门 × 控制器交叉校验 | 任一不过 ⇒ 不交付（`delivered` 需双通过） |

**升级原因分类**（可直接聚合告警）：`code_error` / `assertions_failed` /
`sandbox_timeout` / `sandbox_unavailable`(infra) / `safety_blocked` /
`review_rejected` / `stagnant`。其中 `sandbox_timeout` 与 `sandbox_unavailable`
标记为**基础设施类**，应先排查环境而非归咎模型。

## 提取边界

* 提取的是内核 `more_core/` 全量子树（自包含、相对导入完整）。
* 行业插件（麻将/扫雷）、前端 Dashboard 不在本包内。
* 主仓仍是唯一事实来源：`tools/build.py` 只做复制与打包，不改写代码。
