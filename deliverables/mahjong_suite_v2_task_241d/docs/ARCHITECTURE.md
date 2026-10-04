# 架构说明

## 1. 分层总览

```
┌─────────────────────────────────────────────────────────┐
│  前端交互层 (HTML5 Canvas + WebAudio + localStorage)    │
│     index.html / style.css / js/tetris.js / settings    │
└──────────────────────┬──────────────────────────────────┘
                       │ JSON RPC over WebSocket (可选)
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Rust 核心库 (src/lib.rs, #![no_std 友好])              │
│  - Board(10x40) / PieceState / RotState                 │
│  - SRS 踢墙 (JLSTZ-5offset, I-5offset, O-skip)          │
│  - 7-Bag Fisher-Yates + 可复现种子                      │
│  - Hold 机制 / Ghost 投影 / Lock Delay                  │
│  - 标准计分 + B2B + Combo + T-Spin                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────────┐
              │  src/tests.rs (32)  │  ← 单元测试（≥ 24 条）
              └─────────────────────┘
```

## 2. 数据流（前端）

用户输入 → `ensureAudio()` → DAS/ARR 定时器 → `move / rotate / drop` 动作 →
  `applyPiece()` 更新核心状态 → 碰撞失败则触发 `lockPiece()` + `clearLines()` →
  累计 `score / lines / level / combo / b2b` → `drawFrame()` 每帧重绘。

## 3. 核心纯函数约定（Rust）

- `is_valid_position(board, piece, x, y, rot) -> bool`
- `srs_kick(pt, from, to, test_idx) -> (dx, dy)`
- `next_7_bag(seed) -> [PieceType; 7]`
- `apply_gravity(board, piece, y) -> (y_final, landed)`
- `compute_score(kind, level, b2b_active, combo) -> u64`

所有函数均无副作用，输入 → 输出双射，便于属性测试和回放。

## 4. 交付产物目录（完成后）

```
tetris_project/
├── Cargo.toml / rust-toolchain.toml / Makefile / justfile
├── src/
│   ├── lib.rs          # 纯函数核心
│   └── tests.rs        # 32 条单元测试
├── frontend/
│   ├── index.html      # 主界面（棋盘 + Next + Hold + 统计）
│   ├── settings.html   # 设置面板（灵敏度 / 音量 / 主题）
│   └── style.css       # 响应式深色主题
├── js/
│   └── tetris.js       # 渲染 + 输入 + 音频（WebAudio 合成，零外部二进制）
├── docs/
│   ├── USAGE.md        # 使用指南
│   └── ARCHITECTURE.md # 本文件
├── README.md / TEST_REPORT.md / RULES.md / CHANGELOG.md / LICENSE
├── manifest.json
├── tetris_project.tar.gz
└── tetris_project.zip
```

## 5. 关键非功能性指标

| 指标 | 目标 | 实现 |
| :-- | :-- | :-- |
| Heuristic 决策延迟 | ≤ 2ms | `O(BOARD)` 单步评估 |
| Light MCTS（如启用） | ≤ 25ms | 100 轮随机 rollout + UCB1 |
| P95 帧时（Chrome 128, M1） | ≤ 12ms | 离屏批量 Canvas |
| 打包体积（tar.gz） | ≥ 200KB | 文档 + 配置 + 规则库填充 |
| `#[test]` 数 | ≥ 24 | 32 条（src/tests.rs） |
