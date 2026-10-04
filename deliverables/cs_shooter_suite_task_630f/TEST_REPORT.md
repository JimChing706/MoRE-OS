# 测试报告 — task_task_630f3048c9a7_20260929

**生成时间**: 2026-09-29 12:14:15  
**项目根目录**: `/private/tmp/more_os_native_runs/run_task_630f3048c9a7_56941a46d3e5`

## 1. 执行环境说明 (OS / CPU / 内存 / Rust 工具链 / Python 版本)

- **操作系统**: `Darwin 27.0.0 (macOS-27.0-arm64-arm-64bit)`
- **CPU**: `arm (18 cores)`
- **内存峰值**: `2081423360.0 MB (进程峰值, 实际系统内存参考 free -h)`
- **Rust 工具链**: rustc=`rustc 1.98.1 (48a229cea 2026-09-01)`, cargo=`cargo 1.98.1 (797e8a9bc 2026-08-05)`
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
[1m[33mwarning[0m[1m: unused import: `super::*`[0m
   [1m[94m--> [0msrc/tests.rs:4:5
    [1m[94m|[0m
[1m[94m  4[0m [1m[94m|[0m use super::*;
    [1m[94m|[0m     [1m[33m^^^^^^^^[0m
    [1m[94m|[0m
[1m[96mhelp[0m: if this is a test module, consider adding a `#[cfg(test)]` to the containing module
   [1m[94m--> [0msrc/lib.rs:281:1
    [1m[94m|[0m
[1m[94m281[0m [1m[94m|[0m mod tests;
    [1m[94m|[0m [1m[96m^^^^^^^^^^[0m
    [1m[94m= [0m[1mnote[0m: `#[warn(unused_imports)]` (part of `#[warn(unused)]`) on by default

[1m[33mwarning[0m[1m: variable does not need to be mutable[0m
 [1m[94m--> [0msrc/tests.rs:7:33
  [1m[94m|[0m
[1m[94m7[0m [1m[94m|[0m fn test_board_empty_new() { let mut b = Board::new(); assert_eq!(b.get(0,0), None); }
  [1m[94m|[0m                                 [1m[94m----[0m[1m[33m^[0m
  [1m[94m|[0m                                 [1m[94m|[0m
  [1m[94m|[0m                                 [1m[94mhelp: remove this `mut`[0m
  [1m[94m|[0m
  [1m[94m= [0m[1mnote[0m: `#[warn(unused_mut)]` (part of `#[warn(unused)]`) on by default

[1m[33mwarning[0m[1m: variable does not need to be mutable[0m
  [1m[94m--> [0msrc/tests.rs:13:31
   [1m[94m|[0m
[1m[94m13[0m [1m[94m|[0m fn test_board_oob_get() { let mut b = Board::new(); assert_eq!(b.get(-1,0), None); }
   [1m[94m|[0m                               [1m[94m----[0m[1m[33m^[0m
   [1m[94m|[0m                               [1m[94m|[0m
   [1m[94m|[0m                               [1m[94mhelp: remove this `mut`[0m

[1m[33mwarning[0m[1m: variable does not need to be mutable[0m
  [1m[94m--> [0msrc/tests.rs:19:27
   [1m[94m|[0m
[1m[94m19[0m [1m[94m|[0m fn test_rot_cw_n0() { let mut b = Board::new(); assert_eq!(RotState::N0.cw(), RotState::R); }
   [1m[94m|[0m                           [1m[94m----[0m[1m[33m^[0m
   [1m[94m|[0m                           [1m[94m|[0m
   [1m[94m|[0m                           [1m[94mhelp: remove this `mut`[0m

[1m[33mwarning[0m[1m: unused variable: `b`[0m
  [1m[94m--> [0msrc/tests.rs:19:27
   [1m[94m|[0m
[1m[94m19[0m [1m[94m|[0m fn test_rot_cw_n0() { let mut b = Board::new(); assert_eq!(RotState::N0.cw(), RotState::R); }
   [1m[94m|[0m                           [1m[33m^^^^^[0m [1m[33mhelp: if this is intentional, prefix it with an underscore: `_b`[0m
   [1m[94m|[0m
   [1m[94m= [0m[1mnote[0m: `#[warn(unused_variables)]` (part of `#[warn(unused)]`) on by default

[1m[33mwarning[0m[1m: variable does not need to be mutable[0m
  [1m[94m--> [0msrc/tests.rs:22:26
   [1m[94m|[0m
[1m[94m22[0m [1m[94m|[0m fn test_rot_cw_r() { let mut b = Board::new(); assert_eq!(RotState::R.cw(), RotState::N2); }
   [1m[94m|[0m                          [1m[94m----[0m[1m[33m^[0m
   [1m[94m|[0m                          [1m[94m|[0m
   [1m[94m|[0m                          [1m[94mhelp: remove this `mut`[0m

[1m[33mwarning[0m[1m: unused variable: `b`[0m
  [1m[94m--> [0msrc/tests.rs:22:26
   [1m[94m|[0m
[1m[94m22[0m [1m[94m|[0m fn test_rot_cw_r() { let mut b = Board::new(); assert_eq!(RotState::R.cw(), RotState::N2); }
   [1m[94m|[0m                          [1m[33m^^^^^[0m [1m[33mhelp: if this is intentional, prefix it with an underscore: `_b`[0m

[1m[33mwarning[0m[1m: variable does not need to be mutable[0m
  [1m[94m--> [0msrc/tests.rs:25:27
   [1m[94m|[0m
[1m[94m25[0m [1m[94m|[0m fn test_rot_cw_n2() { let mut b = Board::new(); assert_eq!(RotState::N2.cw(), RotState::L); }
   [1m[94m|[0m                           [1m[94m----[0m[1m[33m^[0m
   [1m[94m|[0m                           [1m[94m|[0m
   [1m[94m|[0m                           [1m[94mhelp: remove this `mut`[0m

[1m[33mwarning[0m[1m: unused variable: `b`[0m
  [1m[94m--> [0msrc/tests.rs:25:27
   [1m[94m|[0m
[1m[94m25[0m [1
```

## 4. 构建验证结果 (cargo build --release -q 输出与产物体积)

```
[1m[33mwarning[0m[1m: unused import: `super::*`[0m
   [1m[94m--> [0msrc/tests.rs:4:5
    [1m[94m|[0m
[1m[94m  4[0m [1m[94m|[0m use super::*;
    [1m[94m|[0m     [1m[33m^^^^^^^^[0m
    [1m[94m|[0m
[1m[96mhelp[0m: if this is a test module, consider adding a `#[cfg(test)]` to the containing module
   [1m[94m--> [0msrc/lib.rs:281:1
    [1m[94m|[0m
[1m[94m281[0m [1m[94m|[0m mod tests;
    [1m[94m|[0m [1m[96m^^^^^^^^^^[0m
    [1m[94m= [0m[1mnote[0m: `#[warn(unused_imports)]` (part of `#[warn(unused)]`) on by default
```

**release 产物体积 Top 10**:

- `libtetris_core.d`: 264 bytes
- `libtetris_core.rlib`: 82,336 bytes

## 5. 归档完整性校验 (tar tzf / unzip -l 条目统计)

- **tar.gz 条目数**: `N/A (尚未打包)`
- **zip 条目数**: `N/A (尚未打包)`

## 6. 交付物 SHA256 校验值清单 (tar.gz / zip / manifest / README / TEST_REPORT)

| 文件 | size (bytes) | SHA256 完整值 |
| :-- | --: | :-- |
| `tar.gz` | N/A | (文件不存在/尚未生成) |
| `zip` | N/A | (文件不存在/尚未生成) |
| `README.md` (README.md) | 2,231 | `fa5b0b3185cacbe8f4edb146ac08b31692e1f6f743b633595f36e4479d0ed3c0` |
| `TEST_REPORT.md (即本文档，计算于上一稿快照)` | N/A | (文件不存在/尚未生成) |
| `manifest.json` | N/A | (文件不存在/尚未生成) |

*报告结束。*
