# 使用指南 — 俄罗斯方块（Rust + HTML5 Canvas）

## 1. 环境要求

| 组件 | 最低版本 | 推荐版本 |
| :-- | :-- | :-- |
| Rust Toolchain | 1.74 (2021 edition) | 1.80+ (stable) |
| Python | 3.10 | 3.12+ |
| 现代浏览器（WebAudio） | Safari 15 / Chrome 102 | Safari 18 / Chrome 128 |
| 可选工具：cargo-tarpaulin | 0.27 | 0.30+ |

## 2. 安装与编译

```bash
# 1) 进入项目根目录
cd tetris_project

# 2) 编译 Rust 核心（debug 快 / release 快）
cargo build
cargo build --release

# 3) 运行单元测试
cargo test -q
cargo test --release -q  # 优化后更快

# 4) 生成覆盖率报告（需 tarpaulin）
cargo tarpaulin --out Html --output-dir ./coverage
open coverage/tarpaulin-report.html
```

## 3. 启动前端

```bash
# 任选一种静态服务器
python3 -m http.server 8080 --directory frontend
# 然后浏览器访问 http://localhost:8080
```

主入口：`frontend/index.html`，设置页：`frontend/settings.html`。

## 4. 操作按键（桌面端）

| 按键 | 功能 |
| :-- | :-- |
| ← / → | 左右移动一格 |
| ↓（按住）| 软降加速 |
| ↑ 或 x / X | 顺时针旋转 |
| z / Z | 逆时针旋转 |
| 空格 | 硬降（立即锁定） |
| c / C / Shift | Hold 暂存 |
| p / P | 暂停 / 继续 |
| r / R | 重新开始 |

## 5. 操作灵敏度调整

进入 `settings.html` 或编辑 localStorage 的 `tetris.settings` 键：

```json
{
  "das": "170",
  "arr": "50",
  "sd":  "40",
  "lock": "500",
  "sfx": "0.7",
  "bgm": "0.35",
  "theme": "classic"
}
```

## 6. 常见问题 FAQ

**Q1：运行 `cargo test` 提示 edition 错误？**
A：确认 `rust-toolchain.toml` 生效，或执行 `rustup override set stable`。

**Q2：浏览器首次无声？**
A：首次交互后才激活 WebAudio（浏览器策略）。按任意游戏键或页面内"打开音效"按钮即可。

**Q3：移动端触控支持？**
A：支持滑动 + 点击区域（见 `frontend/index.html` 底部 touchstart 处理）。

## 7. 命令速查

```bash
make            # 默认：build + test
make build      # cargo build --release
make test       # cargo test --release -q
make serve      # python3 -m http.server 8080 -d frontend
make clean      # cargo clean
```
