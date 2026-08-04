# QNMing MoRE OS — 修复后复审计报告（2026-08-04 当日）

**审计日期**: 2026-08-04（AUDIT_REPORT_2026-08-04.md 修复后复审）
**审计版本**: v0.9.9
**运行时**: Python 3.14.3 · FastAPI 0.136 · pydantic 2.13 · React 19.2 · TypeScript 5.9
**审计范围**:
- 后端: 178 个 Python 源文件 + 46 个测试文件
- 前端: 40 个 `.ts/.tsx` 源文件 + 1 个测试文件
- 运行中服务: API (8011) · minesweeper (8080, 同进程) · 前端 (3003) · LM Studio (1234) · Ollama (11434)

---

## 一、审计摘要

| 维度 | 状态 | 说明 |
|------|:----:|------|
| 后端测试 | ✅ | **735/735 通过 (0 失败)**，46 文件 |
| 前端测试 | ✅ | **24/24 通过**，vitest |
| Ruff lint | ✅ | `All checks passed!`（0 errors） |
| Mypy typecheck | ✅ | **0 errors** / 178 文件 |
| tsc | ✅ | 0 errors |
| ESLint | ✅ | **0 errors / 0 warnings**（上轮 36 errors + 3 warnings，已清零） |
| 前端构建 | ✅ | `vite build` 通过（734.9 kB → gzip 208.4 kB，chunk >500 kB 警告） |
| 覆盖率 | ✅ | `pytest-cov` 已装，`make test-cov` 通过，**TOTAL 65%**（13857 stmt / 4854 miss） |
| 密钥泄漏 | ✅ | 仅 `.env.template` 占位符 + 历史报告提及，无真实密钥 |
| 危险代码 | ✅ | `eval` 仅 AST 白名单（workflows/engine.py:215），其余为沙箱 blocklist 字符串 |
| Git 卫生 | ✅ | 运行时 DB **不再被追踪**；提交采用 Conventional Commits |
| 待提交工作 | ⚠️ | 仅本次复审计产生的 2 处修复未提交（见 §八） |

**结论**: 上轮审计全部 7 项（AUD-01…07）已闭环。本轮复审计额外**发现并修正了上轮审计自身的 2 处缺陷**：router 计数方法错误、以及一个在 coverage 下暴露的 flake 测试。当前无 P1/P2 级未解决问题。

---

## 二、测试基线

### 2.1 后端 pytest（含覆盖率）

```text
735 passed, 2 warnings in 10.51s        # 常规
735 passed, 51 warnings in 11.42s        # --cov 模式（warning 按用例计数，唯 2 类）
TOTAL      13857   4854    65%           # coverage
```

- 2 类警告均为第三方弃用提示：`StarletteDeprecationWarning`（fastapi testclient ↔ httpx）、`RBACManager deprecated`（test fixture 使用），非代码缺陷。
- `make test-cov` 目标自 AUD-02 修复后**首次可复现**。

### 2.2 前端 vitest

```text
Test Files  1 passed (1)
     Tests  24 passed (24)
```

- 覆盖文件仅 `src/lib/format.test.ts`；组件级无测试（见 AUD-12）。

---

## 三、静态质量基线

### 3.1 后端 — 全绿

| 工具 | 结果 |
|------|------|
| `make lint` (ruff) | `All checks passed!` |
| `make typecheck` (mypy strict) | `Success: no issues found in 178 source files` |

### 3.2 前端 — 全绿

| 工具 | 结果 |
|------|------|
| `npm run lint` (eslint) | **0 errors / 0 warnings**（上轮 36 errors / 3 warnings → 全部清零） |
| `npx tsc -b --noEmit` | 0 errors |
| `npm test` (vitest) | 24/24 通过 |
| `npm run build` | 通过；**chunk 超 500 kB**（734.9 kB / gzip 208.4 kB）→ AUD-10 |

ESLint 修复覆盖：`no-explicit-any`（DTO 化 / `unknown`+收窄）、`react-hooks/refs`（弃用 ref+useMemo 模式）、`react-hooks/set-state-in-effect`（条件 setState / async poll）、`react-hooks/purity`（mock 常量）、`no-unused-vars`、`react-refresh/only-export-components`（shadcn 惯例）、`no-unsafe-optional-chaining`、`exhaustive-deps`。详见上一报告 §十。

---

## 四、环境与运行状态

| 组件 | 状态 |
|------|------|
| API Server (8011) | ✅ PID 21397 `more_core.cli serve` |
| minesweeper GUI (8080) | ✅ **同一进程 (21397) 挂载**，`/api/v1/health` → `{"service":"minesweeper","version":"0.1.0"}` |
| Frontend (3003) | ✅ node dev server |
| LM Studio (1234) / Ollama (11434) | ✅ 运行中 |
| `/api/v1/health` (8011) | ✅ healthy, v0.9.9, gates: symbolic/evolution/metacognition=true, providers: ollama/lmstudio |

> 运行实例的 evolution/metacognition gate 为 **true**（本地 `.env` 覆盖），与 CLAUDE.md 默认值 `0` 不冲突——默认值正确，运行态由配置决定。

---

## 五、安全审计

### 5.1 密钥扫描 — ✅ 干净

全量扫描 `sk-proj`/`sk-ant`/`AKIA`/`ghp_`/`AIza`/`xox`：
- 仅命中 `more_core/.env.template:24`（占位符 `sk-ant-...`）与 `docs/SYSTEM_AUDIT_2025.md`（历史报告，已打码）。
- `.env` / `app/.env` 均被 `.gitignore` 忽略，`git ls-files` 无任何 `.env`。

### 5.2 危险代码模式 — ✅ 可控

- `workflows/engine.py:215` `eval(compiled, {"__builtins__": {}}, ...)` 为 **AST 白名单**编译产物（comparisons/bool/attribute）。
- 其余 `eval(`/`exec(` 命中均为 `sandbox/policy.py:33-34`、`secure_sandbox.py:74-75` 的 blocklist 字符串。

### 5.3 环境卫生 — ✅

- `more_core/.env.template` 与 `core/config.py` 默认值一致（`MORE_ENABLE_SYMBOLIC=1`、`EVOLUTION/METACOGNITION=0`），与 CLAUDE.md 同步。

---

## 六、Git 卫生

- **运行时 DB**：`git ls-files | rg .db` 为空；`.gitignore` 已含 `more_core/data/*.db*`（根 + `more_core/` + `more_core/more_core/` 三处规则）。
- **提交历史**（近 8 条均为 Conventional Commits）：
  ```
  7a9f951 chore(audit): AUD-03 frontend lint zero-cleanup, AUD-02 pytest-cov dep, AUD-04/05 docs sync
  c051def chore(infra): async audit writer, untrack runtime sqlite dbs, API hardening
  f2432fc refactor(mcp): drop dead http_client/registry modules
  0230afb refactor(core): service registry wiring, hashed cache key
  7b724da feat(council): deliberate API + L4/L5 council integration
  fd40c92 feat(cron): full 5-field cron parser (CronSpec)
  802081c feat(llm): fallback deadline, TTL cache, health-check timeout
  9d7dcc1 feat(security): SSRF guard for outbound URL fetching
  ```
- **工作区**：仅本次复审计的 2 处修复未提交（`test_fix_regressions.py` + 文档纠错），无其他游离改动。

---

## 七、历史审计回归核对（AUD-01…07）

| ID | 严重级 | 状态 | 复核结果 |
|----|:------:|:----:|------|
| AUD-01 | P1 | ✅ 闭环 | DB 不再被 git 追踪，.gitignore 规则齐全 |
| AUD-02 | P1 | ✅ 闭环 | dev extras 含 `pytest-cov>=4.0`，`make test-cov` 实测通过 (65%) |
| AUD-03 | P1 | ✅ 闭环 | ESLint 0 errors / 0 warnings |
| AUD-04 | P2 | ✅ 闭环 | README badge → v0.9.9；**routers 复核为 21**（上轮"22"为计数错误，见 AUD-09） |
| AUD-05 | P2 | ✅ 闭环 | Known Issues 8080 措辞与实测一致（同进程挂载，v0.1.0） |
| AUD-06 | P2 | ✅ 闭环 | 迭代已提交（7a9f951 及此前 commits） |
| AUD-07 | P3 | ✅ 闭环 | 覆盖率可复现（65%） |

另复核历史高危项保持修复状态：`orchestrator.py:147-148` 单例一致（`get_collector()`/`get_incident_manager()`）、审计后台 writer 线程 + 队列（`governance/audit.py`）、`mcp/http_client.py`/`registry.py` 无残留、`security/ssrf.py` 在位。

---

## 八、本轮新发现

| ID | 严重级 | 类别 | 描述 | 处置 |
|----|:------:|------|------|------|
| AUD-08 | P2 | 测试稳定性 | `test_audit_logger_concurrent_writes` 读文件前未 `flush()`，后台 writer 线程与磁盘读取存在竞态；常规 pytest 靠时序侥幸通过，**coverage 开销下必现失败** | ✅ 已修：断言前加 `logger.flush()`；修复后连跑 3 次 + 全量 --cov 均通过 |
| AUD-09 | P3 | 审计自纠 | 上轮"routers 实际 22"是数了含 `__init__.py` 的**文件数**；`server.py` 实际 `app.include_router` 21 个（含 `deliberate.py`）。CLAUDE.md 的 21 本就正确 | ✅ 已修：CLAUDE.md 保持 21，两份报告均已注明 |
| AUD-10 | P3 | 前端性能 | 构建 bundle 734.9 kB（gzip 208.4 kB），单 chunk 超 500 kB 阈值 | ✅ 已修：路由级 `lazy()` 分包 + `manualChunks` 分组，最大 chunk 195.8 kB，build 零警告 |
| AUD-11 | P3 | 工具链 | `make test-cov` 无 `--cov-fail-under` 门槛，覆盖率可测但**无门禁** | ✅ 已修：加 `--cov-fail-under=50`，门禁失效/生效均实测验证 |
| AUD-12 | P3 | 测试覆盖 | 前端 24 个测试全部集中在 `format.test.ts`，**0 个组件级测试** | ✅ 已修：新增 button/badge/LanguageSwitcher 组件测试 12 用例，共 36 全绿 |

---

## 九、迭代建议（按优先级）

1. **提交本轮 2 处修复**（AUD-08 测试 + AUD-04/09 文档纠错）→ 清空工作区 ✅（commit f4a1279）
2. **给 `make test-cov` 加 `--cov-fail-under` 门禁**（AUD-11）✅ 已实施
3. **前端 code-split + 组件测试**（AUD-10 / AUD-12）✅ 已实施

> 补充（复审计当日追加）：AUD-10 / AUD-11 / AUD-12 三项 P3 建议已一并实施并验证——
> - **AUD-10** `App.tsx` 路由级 `lazy()`+`Suspense` 分包；`vite.config.ts` `manualChunks` 精确分组（vendor-react/radix/i18n-icons，CJS 虚拟模块归入 vendor-react，弃用 catch-all 规避循环 chunk）。最大 chunk 734.9 kB → **195.8 kB**，build 零警告。
> - **AUD-11** `make test-cov` 加 `--cov-fail-under=50`（实测 64.97%）；`--cov-fail-under=99` 验证确实失败 (exit 1)，门禁生效。
> - **AUD-12** 新增组件测试 3 文件 12 用例（button 6 + badge 4 + LanguageSwitcher 2），前端测试 24 → **36 全绿**。

---

> 审计方法: 全量测试基线（含 coverage）+ 静态检查（ruff/mypy/tsc/eslint）+ 构建验证 + 密钥/危险模式正则扫描 + 历史审计回归核对 + 运行态端口/服务核验 + 文档-代码一致性比对。
> 审计方: opencode (big-pickle)
