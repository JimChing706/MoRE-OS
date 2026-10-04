# 测试报告 — task_task_241d109f525b_20260928

**生成时间**: 2026-09-28 08:01:28  
**项目根目录**: `/private/tmp/more_os_native_runs/run_task_241d109f525b_e262ce932e1f`

## 1. 执行环境说明 (OS / CPU / 内存 / Rust 工具链 / Python 版本)

- **操作系统**: `Darwin 27.0.0 (macOS-27.0-arm64-arm-64bit-Mach-O)`
- **CPU**: `arm (18 cores)`
- **内存峰值**: `1907359744.0 MB (进程峰值, 实际系统内存参考 free -h)`
- **Rust 工具链**: rustc=`error: the 'rustc' binary, normally provided by the 'rustc' component, is not applicable to the 'stable-aarch64-apple-darwin' toolchain`, cargo=`cargo 1.98.1 (797e8a9bc 2026-08-05)`
- **Python**: `3.14.3` (`/Users/qnming/AI_Cample/qnm-os-prev-202605211332/.venv/bin/python`)

## 2. 测试范围概述 (构建 + 单元测试 + 归档完整性校验)

| 类别 | 命令 / 检查项 | 说明 |
| :-- | :-- | :-- |
| 构建 | `cargo build --release -q` | 检查 Rust 代码可编译（release 模式） |
| 单测 | `cargo test  --release -q` | 执行 src/tests.rs 全部 #[test] 标注 |
| 归档 | `tar tzf <pkg>.tar.gz` | 校验 gzip 压缩包可正常读取，条目数统计 |
| 归档 | `unzip -l <pkg>.zip`    | 校验 zip 压缩包 CRC + 条目清单可列出 |

## 3. 单元测试结果 (cargo test --release -q 输出与通过率)

- **预期 #[test] 数量**: `≥ 24`，实际静态扫描 `34` 个
```
info: syncing channel updates for stable-aarch64-apple-darwin
error: could not download file from 'https://static.rust-lang.org/dist/channel-rust-stable.toml.sha256' to '/Users/qnming/.rustup/tmp/jpbwbavvuhw2t4x3_file': error downloading file: error sending request for url (https://static.rust-lang.org/dist/channel-rust-stable.toml.sha256): client error (Connect): Connection reset by peer (os error 54)
```

## 4. 构建验证结果 (cargo build --release -q 输出与产物体积)

```
info: syncing channel updates for stable-aarch64-apple-darwin
error: could not download file from 'https://static.rust-lang.org/dist/channel-rust-stable.toml.sha256' to '/Users/qnming/.rustup/tmp/jr6mmzo78zbza1r0_file': error downloading file: error sending request for url (https://static.rust-lang.org/dist/channel-rust-stable.toml.sha256): client error (Connect): Connection reset by peer (os error 54)
```

## 5. 归档完整性校验 (tar tzf / unzip -l 条目统计)

- **tar.gz 条目数**: `N/A (尚未打包)`
- **zip 条目数**: `N/A (尚未打包)`

## 6. 交付物 SHA256 校验值清单 (tar.gz / zip / manifest / README / TEST_REPORT)

| 文件 | size (bytes) | SHA256 完整值 |
| :-- | --: | :-- |
| `tar.gz` | N/A | (文件不存在/尚未生成) |
| `zip` | N/A | (文件不存在/尚未生成) |
| `README.md` (README.md) | 2,231 | `76f370655839c7bd65290ebbcbe7773eae0f2cc1eda5ac27e1b0e5e8c63925e6` |
| `TEST_REPORT.md (即本文档，计算于上一稿快照)` | N/A | (文件不存在/尚未生成) |
| `manifest.json` | N/A | (文件不存在/尚未生成) |

*报告结束。*
