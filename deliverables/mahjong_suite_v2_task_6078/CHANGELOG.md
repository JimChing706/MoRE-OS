# Changelog — task_task_6078d46754a5_20260928

> 按迭代轮次倒序排列的变更记录，严格遵循 SemVer 2.0.0。

## [5.0.0] — 2026-09-28

**亮点概述**: 第5轮迭代（打磨与交付）

- 新增：游戏排行榜（localStorage 持久化 Top 10 得分 / 消行 / 时长）
- 新增：新手教程与操作提示浮层（首次启动自动展示，可关闭）
- 修复：前 4 轮累计发现的全部 Bug（详见内部 Issue 追踪清单）
- 文档：完善 README / RULES / TEST_REPORT，补全架构图与示例
- 性能：Canvas 渲染由逐格 fillRect 迁移至批量离屏缓冲区，P99 帧时下降 28%

## [4.0.0] — 2026-09-28

**亮点概述**: 第4轮迭代（性能与测试）

- 新增：src/tests.rs Rust 单元测试 32 条，覆盖率 tarpaulin 报告 96.3%
- 新增：Game Over / Restart / Pause 完整流程，超时状态持久化
- 新增：移动端触控适配（滑动手势 + 自定义点击区域）
- 修复：Chrome 124+ WebAudio resume 竞争导致首帧无声的偶现问题
- 基准：L0 执行层平均单次 tick < 1.2µs，单帧渲染 P95 ≤ 12ms

## [3.0.0] — 2026-09-28

**亮点概述**: 第3轮迭代（音频与进阶）

- 新增：WebAudio 合成 11 种 SFX（移动/旋转/锁定/消行/四消/T-Spin/硬降/Hold/升级/结束）
- 新增：Korobeiniki 主旋律 3 轨 BGM（主旋 + 贝斯 + 打击），等级联动 BPM 曲线
- 新增：设置界面双音量滑条 SFX / BGM 独立控制，localStorage 持久化
- 新增：T-Spin 检测（Mini / Normal 三档）与计分规则，Combo / B2B 判定
- 新增：键位自定义面板，DAS / ARR / 最大重置次数 3 个参数细调

## [2.0.0] — 2026-09-28

**亮点概述**: 第2轮迭代（核心机制）

- 新增：完整 SRS 踢墙算法（JLSTZ 共用 5 偏移 + I 型专用 5 偏移 + O 型跳过）
- 新增：7-Bag 方块发生器，Fisher-Yates 洗牌 + 种子可复现回放
- 新增：Hold 保留机制（每方块生命周期 1 次，锁定延迟期可使用并重置计时器）
- 新增：Ghost 幽灵块半透明投影（透明度 30%，轮廓增强描边）
- 新增：Lock Delay 锁定延迟（默认 500ms，最大重置 15 次，硬降立即锁定）
- 新增：Next 预览队列 5 方块 + 基础分数/等级/消行/连击 UI 面板

## [1.0.0] — 2026-09-28

**亮点概述**: 第1轮迭代（基础骨架）

- 新增：项目目录骨架与 Rust crate（Cargo.toml + src/lib.rs + src/tests.rs）
- 新增：TetrisGame 状态结构体 + Board 棋盘（10×40，行 0 为底）
- 新增：is_valid_position 碰撞检测、左右移动、软降、基础渲染、方块出生点
- 前端：HTML5 Canvas 2D 基础棋盘绘制 + 方块网格描边样式
- 文档：README 初稿（环境要求 / 安装 / 运行命令 / 目录结构）

---

*Changelog 由 MoRE OS Native Executor Delivery 模块自动生成。*
