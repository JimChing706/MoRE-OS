# 测试报告 — task_task_6078d46754a5_20260928

**生成时间**: 2026-09-28 11:14:39  
**项目根目录**: `/private/tmp/more_os_native_runs/run_task_6078d46754a5_89060bdf2b9a`

## 1. 执行环境说明 (OS / CPU / 内存 / Rust 工具链 / Python 版本)

- **操作系统**: `Darwin 27.0.0 (macOS-27.0-arm64-arm-64bit)`
- **CPU**: `arm (18 cores)`
- **内存峰值**: `2099249152.0 MB (进程峰值, 实际系统内存参考 free -h)`
- **Rust 工具链**: rustc=`error: the 'rustc' binary, normally provided by the 'rustc' component, is not applicable to the 'stable-aarch64-apple-darwin' toolchain`, cargo=`cargo 1.98.1 (797e8a9bc 2026-08-05)`
- **Python**: `3.14.3` (`/Users/qnming/AI_Cample/qnm-os-prev-202605211332/.venv/bin/python3`)

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
info: latest update on 2026-09-03 for version 1.98.1 (48a229cea 2026-09-01)
info: removing previous version of component rust-src
info: removing previous version of component rust-std for target wasm32-unknown-unknown
info: removing previous version of component cargo
info: removing previous version of component clippy
info: removing previous version of component rust-docs
info: removing previous version of component rust-std
info: removing previous version of component rustc
info: removing previous version of component rustfmt
info: downloading 9 components
info: rolling back changes
error: could not rename 'component' file from '/Users/qnming/.rustup/tmp/75p4jh3lyr_6h7op_dir/bk' to '/Users/qnming/.rustup/toolchains/stable-aarch64-apple-darwin/share': Directory not empty (os error 66)
error: could not rename 'component' file from '/Users/qnming/.rustup/tmp/9kqlg86ssysb4t8l_dir/bk' to '/Users/qnming/.rustup/toolchains/stable-aarch64-apple-darwin/share/doc': Directory not empty (os error 66)
error: failed to install component: 'rust-src', detected conflict: 'lib/rustlib/src/rust/library/.cargo/config.toml'
```

## 4. 构建验证结果 (cargo build --release -q 输出与产物体积)

```
info: syncing channel updates for stable-aarch64-apple-darwin
info: latest update on 2026-09-03 for version 1.98.1 (48a229cea 2026-09-01)
info: removing previous version of component rust-src
info: removing previous version of component rust-std for target wasm32-unknown-unknown
info: removing previous version of component cargo
info: removing previous version of component clippy
info: removing previous version of component rust-docs
info: removing previous version of component rust-std
info: removing previous version of component rustc
info: removing previous version of component rustfmt
info: downloading 9 components
info: rolling back changes
error: could not rename 'component' file from '/Users/qnming/.rustup/tmp/bfonbmklw898snht_dir/bk' to '/Users/qnming/.rustup/toolchains/stable-aarch64-apple-darwin/share': Directory not empty (os error 66)
error: could not rename 'component' file from '/Users/qnming/.rustup/tmp/uyxuug8sksj86f4f_dir/bk' to '/Users/qnming/.rustup/toolchains/stable-aarch64-apple-darwin/share/doc': Directory not empty (os error 66)
error: failed to install component: 'rust-src', detected conflict: 'lib/rustlib/src/rust/library/.cargo/config.toml'
```

## 5. 归档完整性校验 (tar tzf / unzip -l 条目统计)

- **tar.gz 条目数**: `N/A (尚未打包)`
- **zip 条目数**: `N/A (尚未打包)`

## 6. 交付物 SHA256 校验值清单 (tar.gz / zip / manifest / README / TEST_REPORT)

| 文件 | size (bytes) | SHA256 完整值 |
| :-- | --: | :-- |
| `tar.gz` | N/A | (文件不存在/尚未生成) |
| `zip` | N/A | (文件不存在/尚未生成) |
| `README.md` (README.md) | 2,231 | `8b9329e9509a2b1ca87f9050c174c07a0fabce047a314a33197f6c52a3023d52` |
| `TEST_REPORT.md (即本文档，计算于上一稿快照)` | N/A | (文件不存在/尚未生成) |
| `manifest.json` | N/A | (文件不存在/尚未生成) |

*报告结束。*
