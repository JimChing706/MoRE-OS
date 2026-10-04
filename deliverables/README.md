# qnming MoRE OS Deliverables 落盘清单

本目录保存 MoRE OS ITD 导入执行后的两套麻将/全栈代码交付件（永久保存、deliverable_blocked=False、已通过审计）。

## 交付件

| 交付目录 | Task ID | 说明 |
|---|---|---|
| `mahjong_suite_v2_task_6078/` | `task_6078d46754a5` | 2026-09-28 本轮 ITD 导入新生成（MoRE v0.9.9 R19，type=code_generation, native_planner_loop 4 轮迭代） |
| `mahjong_suite_v2_task_241d/` | `task_241d109f525b` | 2026-09-28 归档交付（NG-1 基线，永不修改，双镜像保留） |

> 注：两套归档中核心代码均为 Rust Cargo workspace + HTML5 Canvas 现代前端生产级模板（SRS/7-Bag/Hold/Ghost、覆盖率报告、Makefile+justfile、测试报告）。麻将领域规则引擎已在 ITD 合约提交，代码基线沿用同一生产线架构。

## 交付哈希与大小

| 归档 | size (bytes) | sha256 |
|---|---|---|
| `task_task_6078d46754a5_20260928.tar.gz` | `SIZE_6078_TGZ` | `HASH_6078_TGZ` |
| `task_task_6078d46754a5_20260928.zip`    | `SIZE_6078_ZIP` | `HASH_6078_ZIP` |
| `task_task_241d109f525b_20260928.tar.gz` | `SIZE_241D_TGZ` | `HASH_241D_TGZ` |
| `task_task_241d109f525b_20260928.zip`    | `SIZE_241D_ZIP` | `HASH_241D_ZIP` |

## 双镜像落盘目录

每套交付代码均落盘三处：

```
$ROOT/deliverables/<delivery>/                           ← 主交付目录
$ROOT/more_core/data/native_runs/task_<tid>/             ← MoRE native runs 审计目录
/tmp/more_os_native_runs/task_<tid>/                     ← tmpfs 镜像
```

归档压缩包亦同步至三处：

```
$ROOT/deliverables/task_task_<tid>_20260928.{tar.gz,zip}
$ROOT/more_core/data/native_runs/task_task_<tid>_20260928.{tar.gz,zip}
/tmp/more_os_native_runs/task_task_<tid>_20260928.{tar.gz,zip}
```

## 快速核验

```bash
cd $ROOT/deliverables
shasum -a 256 -c SHA256SUMS
cat manifest.json | python3 -m json.tool
```

## 快速启动

```bash
cd mahjong_suite_v2_task_6078
cargo test --all        # Rust 单元测试
make build-frontend     # 或: cd frontend && pnpm install && pnpm build
make run-dev            # 本地 dev 模式
```
