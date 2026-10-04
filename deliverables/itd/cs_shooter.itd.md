---
title: CS 风格多人射击游戏（Rust 后端 + Web 前端）
version: 1.0.0
author: qnming
created: 2026-09-29T09:30:00Z
type: code_generation
priority: high
deliverable_kind: code
tags: ["game", "rust", "frontend", "multiplayer"]
target_confidence: 75.0
max_iterations: 20
timeout_s: 900.0
allow_self_improvement: true
require_metacognitive: true
kill_on_diverge: true
---

# Executive Summary

使用 Rust 语言 + Web 前端技术栈，开发一款 CS（Counter-Strike）风格的多人在线射击游戏。
要求系统自主完成多轮需求迭代与技术优化，开展长周期系统性开发工作，最终一次性输出
完整、可运行、可验收的成熟成果（含源码、构建脚本、自动化测试与文档）。

# Requirements

## REQ-001: 服务端权威架构

**Priority:** HIGH
**Description:** 游戏核心逻辑必须运行在 Rust 服务端，客户端只发送输入意图，命中与比分不得由客户端裁决。

**Acceptance Criteria:**
- [ ] Rust 服务端持有权威世界状态（位置/血量/弹药/回合）
- [ ] 客户端仅发送输入意图，服务端广播状态快照
- [ ] 存在服务端侧的命中校验路径

## REQ-002: 角色移动与射击

**Priority:** HIGH
**Description:** 实现第一人称移动、跳跃下蹲、视角旋转、射线命中判定、开火与后坐力、换弹。

**Acceptance Criteria:**
- [ ] 支持 WASD 移动与鼠标视角
- [ ] 支持开火、换弹与弹药计数
- [ ] 命中判定基于射线与胶囊体求交

## REQ-003: 回合制竞技玩法

**Priority:** HIGH
**Description:** 实现 CS 风格回合制：购买阶段、回合开始/结束、进攻防守双方计分与胜负判定。

**Acceptance Criteria:**
- [ ] 存在购买阶段与回合状态机（WARMUP/BUY/LIVE/END）
- [ ] 支持进攻方与防守方计分
- [ ] 回合结束后正确重置状态

## REQ-004: 网络同步与多客户端

**Priority:** HIGH
**Description:** 实现固定 tick 的服务端循环与客户端同步/插值，支持至少 2 名玩家同房对战。

**Acceptance Criteria:**
- [ ] 服务端以固定 tick 率推进世界
- [ ] 客户端对远端实体做插值平滑
- [ ] 至少 2 个客户端可进入同一房间对战

## REQ-005: Web 前端渲染与 HUD

**Priority:** MEDIUM
**Description:** 使用 Web 技术栈渲染 3D 场景与 HUD（准星、血量、弹药、比分、击杀提示）。

**Acceptance Criteria:**
- [ ] 可渲染地图与玩家实体
- [ ] HUD 显示血量/弹药/比分
- [ ] 支持指针锁定与灵敏度设置

## REQ-006: 多轮自主迭代

**Priority:** MEDIUM
**Description:** 系统需自主完成不少于 3 轮"实现 → 验证 → 修复"迭代，并记录每轮产出与结论。

**Acceptance Criteria:**
- [ ] 存在 ≥3 轮迭代记录
- [ ] 每轮记录问题、修复动作与验证结果
- [ ] 迭代记录与最终交付物一致

## REQ-007: 性能优化与量化

**Priority:** MEDIUM
**Description:** 给出帧率与 tick 率指标，完成至少一项可量化的性能优化并附前后对比。

**Acceptance Criteria:**
- [ ] 提供性能指标基线
- [ ] 提供优化后对比数据
- [ ] 说明优化手段与适用边界

## REQ-008: 测试与交付完整性

**Priority:** HIGH
**Description:** 核心逻辑具备自动化测试，交付物可一键构建运行，并附带完整文档。

**Acceptance Criteria:**
- [ ] cargo test 通过
- [ ] 前端构建命令通过
- [ ] 提供 README 与构建/启动脚本

# Deliverable Contract

**Kind:** code
**Required Dimensions:** core_output, reasoning, tests
**Minimum Output Length:** 400

**Acceptance Criteria:**
- [ ] Rust 服务端可编译通过（cargo build --release 无错误）
- [ ] 核心逻辑单元测试全部通过（cargo test）
- [ ] 前端可构建通过（npm run build 或等价命令）
- [ ] 至少 2 名玩家可进入同一房间并进行一轮完整对战
- [ ] 命中判定由服务端给出，存在可验证的服务端权威路径
- [ ] 包含 README 与构建/启动脚本，可一键运行
- [ ] 存在 ≥3 轮迭代记录，含每轮问题、修复与验证结果
- [ ] 存在至少 1 项性能优化的量化前后对比

# Kill Criteria

- Rust 工程无法编译且 3 轮修复内未收敛
- 命中判定完全由客户端裁决，服务端无权威校验
- 交付物中缺少可运行入口或构建脚本

# Resource Budget

**Estimated Tokens:** 120,000
**Estimated Duration:** 180 minutes
**Max Iterations:** 20
