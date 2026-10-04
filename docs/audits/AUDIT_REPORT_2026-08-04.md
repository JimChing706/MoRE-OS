# QNMing MoRE OS — 系统性审计报告

**审计日期**: 2026-08-04
**审计版本**: v0.9.9
**运行时**: Python 3.14.3 · Node v26.5.0 · FastAPI 0.136 · pydantic 2.13
**审计范围**:
- 后端: 178 个 Python 源文件 (31,306 LOC) + 46 个测试文件
- 前端: 40 个 `.ts/.tsx` 源文件
- 运行中服务: API (8011) · 前端 (3003) · minesweeper (8080) · LM Studio (1234) · Ollama (11434)

---

## 一、审计摘要

| 维度 | 状态 | 说明 |
|------|:----:|------|
| 后端测试 | ✅ | **735/735 通过 (0 失败)**，46 文件 |
| 前端测试 | ✅ | **24/24 通过**，vitest |
| Ruff lint | ✅ | **0 errors**（上次审计 151 errors） |
| Mypy typecheck | ✅ | **0 errors** / 178 文件（上次审计 520 errors） |
| tsc | ✅ | **0 errors** |
| ESLint | ✅ | **0 errors / 0 warnings**（审计时 36 errors + 3 warnings，已修复，见 §九） |
| 密钥泄漏 | ✅ | 未发现真实密钥（仅测试 fixture + 模板占位符） |
| 危险代码 | ✅ | `eval` 仅 AST 白名单 / 沙箱 blocklist 语境 |
| 覆盖率工具 | ✅ | `pytest-cov` 已装，coverage **65%**（审计时未安装，已修复，见 §九） |
| 待提交工作 | ⚠️ | **68 文件 (+1407/−877) 未提交**，含 3 个新测试文件 |

**结论**: 代码质量较 v0.8.0 审计有**质的提升**（mypy 520→0，ruff 151→0，后端测试全绿）。当前核心风险不在代码正确性，而在**工程卫生**：覆盖工具缺失、运行时 DB 入库、前端 lint 债、大量工作未提交。

---

## 二、测试基线

### 2.1 后端 pytest

```text
735 passed, 4 warnings in 11.87s
```

- 测试文件: 46（含新增 `test_config.py`, `test_cron_scheduler.py`, `test_ssrf.py`）
- 4 个 warning 均为第三方库弃用提示（starlette/httpx、websockets.legacy、RBACManager deprecated），非代码缺陷。

### 2.2 前端 vitest

```text
Test Files  1 passed (1)
     Tests  24 passed (24)
```

- 上次审计的 2 个浮点精度失败（NumberPrecision）已修复。

---

## 三、静态质量基线

### 3.1 后端 — 全绿

| 工具 | 结果 |
|------|------|
| `make lint` (ruff) | `All checks passed!` |
| `make typecheck` (mypy strict) | `Success: no issues found in 178 source files` |

较 v0.8.0 审计报告（ruff 151 errors / mypy 520 errors）:**全部清零**。mypy 类错误（`"MoRECore" has no attribute "X"`、泛型 dict、`StreamWriterProtocol` 私有 API）均已在迭代中解决。

### 3.2 前端 — ESLint 39 problems (36 errors, 3 warnings)

| 类别 | 数量 | 文件 |
|------|:----:|------|
| `@typescript-eslint/no-explicit-any` | ~22 | moreEngine.ts(7), ProjectOutputReview.tsx(5), useMahjongSocket.ts(4), apiService.ts(2), RequirementsImporter.tsx(1), TaskPanel.tsx(1), MahjongGame.tsx(1) |
| `react-hooks/purity` (Date.now in render) | 4 | SafetyPanel.tsx (mock 数据硬编码在渲染期) |
| `react-hooks/set-state-in-effect` | 3 | LayerVisualizer.tsx, SystemDashboard.tsx, MahjongGame.tsx |
| `@typescript-eslint/no-unused-vars` | 3 | MahjongGame.tsx (`e` 未使用) |
| `react-refresh/only-export-components` | 2 | ui/badge.tsx, ui/button.tsx |
| `no-unsafe-optional-chaining` | 1 | MahjongGame.tsx:202 |
| `react-hooks/immutability` | 1 | useMahjongSocket.ts (`connect` 先于声明访问) |
| `react-hooks/exhaustive-deps` | 3 (warning) | ProjectOutputReview.tsx, RequirementsImporter.tsx, SystemDashboard.tsx |

> `SafetyPanel.tsx` 的 `Date.now()` 在渲染期执行是真实缺陷：mock 时间戳每次重渲染都会漂移，应改为模块常量或 `useMemo`。

---

## 四、环境与运行状态

| 组件 | 状态 |
|------|------|
| API Server (8011) | ✅ PID 21397 `more_core.cli serve` |
| Frontend (3003) | ✅ node dev server |
| minesweeper GUI (8080) | ✅ **由 API server 进程内挂载**，`/api/v1/health` 返回 v0.1.0 |
| LM Studio (1234) / Ollama (11434) | ✅ 运行中 |
| `/api/v1/health` (8011) | ✅ healthy, v0.9.9, LLM providers: ollama/lmstudio |

### 4.1 ⚠️ CLAUDE.md "Known Issues" 已过时

原文: 「扫雷 GUI (8080) 端口被系统占用，不影响核心」。
实测: 8080 已被 **API server 同一进程 (21397)** 挂载的 minesweeper 插件占用且服务正常，并非"被系统占用"。文档需更新。

---

## 五、安全审计

### 5.1 密钥扫描 — ✅ 干净

对 `app/`、`more_core/` 全量扫描 `sk-proj` / `sk-ant` / `AKIA` / `ghp_` / `AIza` / `xox` 模式:
- 仅命中 `tests/test_skill_config.py:58`（`ghp_abc123` fixture）与 `.env.template`（占位符）。
- **无真实密钥入库**，v0.8.0 的密钥泄露修复保持有效。

### 5.2 危险代码模式 — ✅ 可控

- `workflows/engine.py:215` 的 `eval()` 为 **AST 白名单**（comparisons/bool/attribute 仅），非任意执行。
- 其余 `eval(`/`exec(` 命中均为 `secure_sandbox.py` / `policy.py` 的 **blocklist 字符串**。
- 新增 `security/ssrf.py`（未提交迭代）质量高: 封禁 RFC1918/loopback/link-local/CGNAT + `*.localhost/.local/.internal`；**明确不做 DNS 分类**（避免 VPN/NAT 误报），权衡记录在 docstring。

### 5.3 历史审计回归验证 — ✅ 已修复

- IncidentManager / MetricsCollector 单例不一致（2026-05-02 H 级）: `orchestrator.py:147-148` 已改为 `get_collector()` / `get_incident_manager()`。
- 审计日志升级为**后台 writer 线程 + 队列**（`governance/audit.py`），事件循环不再被文件 I/O 阻塞。
- `mcp/http_client.py`、`mcp/registry.py` 已删除，**全仓无残留引用**，`mcp/__init__.py` 同步清理。

---

## 六、架构与一致性

### 6.1 🔴 运行时 SQLite DB 被 git 追踪（P1）

**问题**: `more_core/data/*.db{, -shm, -wal}`（10 个文件，共 480K）被 git 追踪。根 `.gitignore` 的 `data/*.db` 规则**只匹配根 `data/`，不匹配 `more_core/data/`**。

**影响**:
- 每次运行服务都会产生 runtime diff（本次审计即见 `memory.db` / `outputs.db` 被修改甚至 `outputs.db` 已被 staged）。
- 存在把**真实运行数据/敏感内容**误提交进版本库的风险。

**建议**: `git rm --cached more_core/data/*.db*`，在 `.gitignore` 增加 `more_core/data/*.db*`，保留 `audit.jsonl`（未追踪）策略。

### 6.2 🔴 `make test-cov` 失效（P1）

**问题**: Makefile:108-110 调用 `pytest --cov=more_core`，但 `pytest-cov`/`coverage` 未声明在 `pyproject.toml` dev extras 也未安装。实测:

```text
python -m pytest: error: unrecognized arguments: --cov=more_core
make: *** [test-cov] Error 4
```

**影响**: 覆盖率门禁形同虚设；历次审计报告中的"覆盖率"数字不可复现。

**建议**: dev extras 增加 `pytest-cov>=4` 并重装。

### 6.3 ⚠️ 文档版本漂移（P2）

| 位置 | 声称 | 实际 |
|------|------|------|
| `README.md:7` badge | v0.6.0-alpha | v0.9.9 |
| `CLAUDE.md` 模块表 | 21 routers | **21（正确）**——审计初判"实际 22"是把 `__init__.py` 计入 router 数，`server.py` 实际 `include_router` 21 个（含 `deliberate.py`） |

### 6.4 ⚠️ 大量未提交迭代（P2）

未提交变更 68 文件 (+1407/−877)，主题清晰且已全绿验证:
- **cron**: 全 5 字段解析器 `CronSpec`（`*/n`, `a-b`, `a,b,c`, 命名星期）
- **llm/manager**: 串行 fallback 总 deadline 90s、缓存 TTL 300s、健康检查超时 5s、失败计数 TTL——修掉"N×5×120s 最长 750s 挂死"病理
- **orchestrator**: service registry 注册 16 个子系统 + 状态 RUNNING、缓存 key 全查询 SHA-256、meta-orchestrator 激活时跳过冗余 LayerRouter pass
- **security/ssrf.py** + `test_ssrf.py`(17 用例)
- **council** deliberate API (`api/routers/deliberate.py`)
- **deepseek provider**: 110 行重构

**风险**: 一个完成度很高的迭代滞留工作区，一旦误操作即丢失。建议尽快按 Conventional Commits 提交。

---

## 七、发现汇总

| ID | 严重级 | 类别 | 描述 | 建议 |
|----|:------:|------|------|------|
| AUD-01 | P1 | 工程卫生 | 运行时 DB (10 文件, 480K) 被 git 追踪 | `git rm --cached` + 补 `.gitignore` 规则 |
| AUD-02 | P1 | 工具链 | `make test-cov` 因缺 `pytest-cov` 失效 | 补 dev 依赖并重装 |
| AUD-03 | P1 | 前端质量 | ESLint 36 errors/3 warnings，含渲染期 `Date.now()` | 见 3.2 分类修复 |
| AUD-04 | P2 | 文档 | README badge 0.6.0 过时；routers 21 正确（审计误数 `__init__.py`） | badge 更新为 v0.9.9 |
| AUD-05 | P2 | 文档 | 8080 "被系统占用" 描述过时 | 更新 Known Issues |
| AUD-06 | P2 | 流程 | 68 文件完整迭代未提交 | 尽快提交 |
| AUD-07 | P3 | 观测 | 覆盖率不可测（依赖缺失） | 随 AUD-02 解决 |

**正面确认**: 后端静态质量全绿、密钥干净、危险代码可控、历史高危项（单例、审计 I/O、私有 API）已修复、SSRF 新增守卫质量高。

---

## 八、迭代建议（按优先级）

1. **提交当前迭代**（AUD-06）→ 清除工作区风险
2. **修 DB 追踪**（AUD-01）→ 杜绝运行数据入库
3. **补 `pytest-cov` 依赖**（AUD-02）→ 恢复覆盖率门禁
4. **前端 ESLint 清零**（AUD-03）→ 分三类：`any`→具体类型、`Date.now`→useMemo/常量、set-state-in-effect→回调驱动
5. **文档同步**（AUD-04/05）

---

> 审计方法: 全量测试基线 + 静态检查 + 密钥/危险模式正则扫描 + 历史审计回归核对 + 运行态端口/服务核验 + 文档-代码一致性比对。
> 审计方: opencode (big-pickle)

---

## 九、修复跟进（2026-08-04，审计当日）

| ID | 严重级 | 状态 | 修复内容 |
|----|:------:|:----:|------|
| AUD-01 | P1 | ✅ 已修复 | `git rm --cached` 运行时 DB + `.gitignore` 补 `more_core/data/*.db*`（commit c051def） |
| AUD-02 | P1 | ✅ 已修复 | dev extras 增加 `pytest-cov>=4.0`；实测 `735 passed`，coverage **65%** |
| AUD-03 | P1 | ✅ 已修复 | 前端 ESLint 36 errors/3 warnings → **0 errors / 0 warnings**（见 §十 修复明细） |
| AUD-04 | P2 | ✅ 已修复 | README badge → `v0.9.9`；routers 复核为 **21**（`server.py` 21 个 `include_router`，`__init__.py` 不计入；审计初判 22 为计数错误） |
| AUD-05 | P2 | ✅ 已修复 | CLAUDE.md Known Issues 更新为"API server 进程内挂载" |
| AUD-06 | P2 | ✅ 已修复 | 本次迭代 + 修复全部按 Conventional Commits 提交 |
| AUD-07 | P3 | ✅ 已修复 | 随 AUD-02 解决（覆盖率可复现） |

### 十、ESLint 修复明细（AUD-03）

| 类别 | 修复方式 |
|------|------|
| `no-explicit-any`（22 处） | moreEngine.ts 新增 `ReasoningChainStepDto`/`MemoryEntryDto`/`IncidentDto` DTO；apiService/ProjectOutputReview 改 `unknown` + 收窄；TaskPanel/RequirementsImporter `Record<string, any>`→`unknown` |
| `react-hooks/purity`（Date.now） | SafetyPanel mock 数据提为模块常量 `MOCK_NOW`/`MOCK_AUDIT_LOGS` |
| `react-hooks/set-state-in-effect` | LayerVisualizer 改 `useMemo` 派生；SystemDashboard 用条件 setState 模式；MahjongGame 轮询 effect 改 `cancelled` guard + async poll |
| `react-hooks/refs` | SystemDashboard 弃用 ref+useMemo；useMahjongSocket `connectRef` 同步移入 `useEffect` |
| `no-unused-vars` | MahjongGame `catch (e)`→`catch {}` |
| `react-refresh/only-export-components` | ui/badge、ui/button 加文件级 disable 注释（shadcn 变体导出惯例） |
| `no-unsafe-optional-chaining` | MahjongGame `canCall` 重写为类型安全判空 + `in` 运算 |
| `exhaustive-deps`（3 warnings） | ProjectOutputReview 补 deps；RequirementsImporter 补 deps |
