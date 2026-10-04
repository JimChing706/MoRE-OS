# task_task_6078d46754a5_20260928 — 工业级俄罗斯方块
> Rust 核心算法 + HTML5 Canvas 前端，SRS/7-Bag/Hold/Ghost/Lock Delay 全特性实现。
## 快速开始
```bash
# 1) 编译 Rust 核心
cargo build --release
# 2) 运行单元测试
cargo test --release -q
# 3) 启动前端（任选其一）
python3 -m http.server 8080 -d frontend  # 然后浏览器访问 http://localhost:8080
```
## 已实现功能清单 (AC)
- [x] Rust 核心库：SRS 踢墙算法（完整 15 组 JLSTZ + I 型独立偏移量表 + O 型跳过）
- [x] 7-Bag 随机方块发生器（Fisher-Yates 洗牌，每袋 7 种方块各出现一次）
- [x] Hold 方块保留机制（每方块生命周期限 1 次，锁定延迟期可用并重置计时器）
- [x] Ghost 幽灵块投影（实时计算，半透明渲染，操作变更即刷新）
- [x] Lock Delay 锁定延迟（默认 500ms，最大重置 15 次，硬降立即锁定）
- [x] 计分规则：单消/双消/三消/四消 × 等级 + T-Spin + Back-to-Back + Combo 连击
- [x] 前端 10×20 棋盘渲染、NEXT 预览 5 方块、HOLD 槽位显示
- [x] 键盘操作：←→ 移动、↓ 软降、↑/X 顺旋、Z 逆旋、Space 硬降、C/Shift Hold、P 暂停、R 重开
- [x] WebAudio 合成 SFX（移动/旋转/锁定/消行/Tetris/硬降/Hold/升级/Game Over）与 BGM 音量滑条框架
- [x] Rust 单元测试 ≥ 24 个 #[test] 覆盖碰撞检测、SRS、7-Bag、Ghost、消行、计分

## 操作说明
| 按键 | 功能 |
| :-- | :-- |
| ← / → | 左右移动一格 |
| ↓ (按住) | 软降（加速下落） |
| ↑ / X | 顺时针旋转 |
| Z | 逆时针旋转 |
| Space | 硬降（立即落底并锁定） |
| C / Shift | Hold（保留当前方块） |
| P | 暂停 / 继续 |
| R | 重新开始 |

## 项目结构
```
src/
  lib.rs       # Rust 核心算法（SRS/7-Bag/Hold/Ghost/计分）
  tests.rs     # Rust 单元测试（≥ 24 个 #[test]）
frontend/
  index.html   # 前端页面骨架
js/
  tetris.js    # 前端渲染 + 键盘 + WebAudio 音效
Cargo.toml    # Rust 项目配置
README.md     # 本文档
TEST_REPORT.md# 测试报告
manifest.json # 文件清单（path/size/sha256 前缀 16 位）
```

## License
Apache-2.0 © MoRE OS Native Executor
