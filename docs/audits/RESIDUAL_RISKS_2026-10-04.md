# MoRE OS 残留风险清单（逐条列明 · 2026-10-04 复核）

## 修复状态（2026-10-04 更新）

按建议顺序推进后，本清单状态如下：

| ID | 级别 | 问题 | 状态 |
|----|:----:|------|:----:|
| R-01 | 🔴 P0 | `app/src/lib/` 被 gitignore 吞掉 | ✅ 已修（规则收窄为 `/lib/`，3 个文件已入库） |
| R-02 | 🔴 P0 | MCP `tools/call` 认证可绕过 | ✅ 已修（全方法鉴权，仅 initialize 免令牌） |
| R-03 | 🔴 P0 | RBAC 身份取自请求体 | ✅ 已修（身份改为凭证派生；新增 `MORE_RBAC_STRICT`） |
| R-04 | 🔴 P0 | 模板路由误判 docs/metrics/fps | ✅ 已修（强弱信号分层，11/11 用例正确） |
| R-05 | 🟠 P1 | cs_shooter 仅 placeholder | 🟡 部分（logic 闸门已拦截；模板未接 LLM） |
| R-06 | 🟠 P1 | 缓存跨主体复用 / 无法重生成 | ✅ 已修（键纳入主体 + 代码任务默认绕过） |
| R-07 | 🟠 P1 | 子任务无调度器 | ✅ 已修（REQ 子任务真实派发 + 父任务门控，见批次2） |
| R-08 | 🟠 P1 | best-of-k 串行 | 🟡 并行能力已实现（默认串行，见批次2 §5） |
| R-09 | 🟠 P1 | 不强制断言 | 🟡 部分（`expected_symbols`/`assertions` 时强制；未全量自动推导） |
| R-10 | 🟠 P1 | 沙箱非安全边界 | ✅ 已加固（批次2 §6） |
| R-11 | 🟡 P2 | 超时/取消无遥测 | ✅ 已修（三个入口补 CancelledError 落库） |
| R-12 | 🟡 P2 | 工作目录被删 | ✅ 已修（失败/拦截保留，`MORE_KEEP_RUN_DIR` 强制保留） |
| R-13 | 🟡 P2 | 内存峰值单位错误 | ✅ 已修（macOS 字节 / Linux KB 分流） |
| R-14 | 🟡 P2 | 重复 adjudicate + 噪声 | 🟡 部分（重复调用已去重；convergence 未改） |
| R-15 | 🟡 P2 | 前端未接遥测/无鉴权头 | ✅ 已修（统一 apiClient + 遥测面板，见批次2 §7） |
| R-16 | 🟡 P3 | `/health` 404 | ✅ 已修（307 → `/api/v1/health`） |
| R-17 | 🟡 P3 | 短密钥不再脱敏 | 📝 有意取舍（已在报告说明） |
| R-18 | 🟡 P3 | 未提交改动 / lint 债务 | 🟡 部分（本批新增文件 ruff clean） |
| R-19 | 🟡 P3 | llama.cpp 自动拉起 OOM | ✅ 已修（改为 `MORE_START_LLAMACPP=1` 显式启用） |

**剩余未修（按优先级）**：R-05 后半（模板接 LLM）→ R-14 后半（convergence 指标）。

---

**说明**：本清单只收录**当前仍然存在**的问题，每条都标注了复核证据与复核方式。
已修复项（API Key 全流程、产出正确性闸门、交付台账、可观测性采集）不在此列。

**复核方式**：本机 API（`127.0.0.1:8011`）+ 源码检查 + 最小复现脚本。

---

## 0. 风险总览

| ID | 级别 | 问题 | 复核结论 |
|----|:----:|------|:--------:|
| R-01 | 🔴 P0 | `app/src/lib/` 被 gitignore 吞掉，新克隆前端无法构建 | 仍存在 |
| R-02 | 🔴 P0 | MCP `tools/call` 认证可绕过（无 token 直接执行工具） | 仍存在 |
| R-03 | 🔴 P0 | RBAC 主体身份取自请求体 `context.actor`，可冒充管理员 | 仍存在 |
| R-04 | 🔴 P0 | 模板路由正则无词边界，`docs/metrics/statistics/fps` 全被误判为 CS 射击 | 仍存在 |
| R-05 | 🟠 P1 | cs_shooter 模板只产出 placeholder 空壳（未接 LLM） | 部分缓解 |
| R-06 | 🟠 P1 | 任务级缓存按 query 哈希跨主体复用，且无法重生成 | 仍存在 |
| R-07 | 🟠 P1 | 子任务无调度器：REQ 子任务长期 pending，父任务却 completed | ✅ 已修复（批次2） |
| R-08 | 🟠 P1 | best-of-k 串行执行（token ×2.9–3.1） | 🟡 并行能力已实现（默认串行，批次2 §5） |
| R-09 | 🟠 P1 | 默认不强制断言，"能跑不报错"即 pass | 仍存在 |
| R-10 | 🟠 P1 | Python 沙箱不是安全边界（黑名单子串匹配） | ✅ 已加固（AST 判定 + 全 argv + 路径/环境加固，见批次2 §6） |
| R-11 | 🟡 P2 | 遥测只在 LLM 调用**完成**时落库，超时/取消调用无记录 | 仍存在 |
| R-12 | 🟡 P2 | 执行工作目录被执行完的 `finally` 删除，中间产物不可复核 | 仍存在 |
| R-13 | 🟡 P2 | TEST_REPORT 内存峰值单位错误（约 2.2e9 MB） | 仍存在 |
| R-14 | 🟡 P2 | L0 重复调用 `adjudicate_codegen`；convergence 对平凡任务报 oscillating | 仍存在 |
| R-15 | 🟡 P2 | 前端未接真实遥测 / 无鉴权头 | ✅ 已修复（批次2 §7） |
| R-16 | 🟡 P3 | 用户可见路径 `/health` 不存在（正确为 `/api/v1/health`） | 仍存在 |
| R-17 | 🟡 P3 | 脱敏权衡：≤14 字符的无引号密钥不再脱敏 | 有意取舍 |
| R-18 | 🟡 P3 | 大量未提交改动；全仓 ruff 历史告警约 80 条 | 仍存在 |
| R-19 | 🟡 P3 | `make` 因 Xcode 许可不可用；27B llama.cpp 会 OOM 拖垮 API | 环境限制 |

---

## 1. P0 — 发布/安全阻断

### R-01 🔴 `app/src/lib/` 被 `.gitignore` 吞掉，新克隆前端无法构建

**证据**
```
$ git check-ignore -v app/src/lib/utils.ts
.gitignore:18:lib/    app/src/lib/utils.ts
$ git ls-files app/src/lib | wc -l
0
```
`app/src/lib/` 含 `utils.ts`（shadcn `cn()`）、`format.ts`、`format.test.ts`；
15 个文件 `import '@/lib/utils'`、7 个 `import '@/lib/format'`。

**影响**：任何 `git clone` / CI checkout 得到的前端都缺少这些模块，
`npm run build` / `tsc -b` / `npm test` 全部失败（本地因文件存在而"看似正常"）。

**建议**：`.gitignore:18` 的 `lib/` 收窄为 `/lib/`；`git add -f app/src/lib/`。

---

### R-02 🔴 MCP `tools/call` 认证可绕过

**证据**（复核脚本，设 `MORE_MCP_KEY=supersecret`）
```
无 token 直接 tools/call -> 已执行(BYPASS)
```
`mcp/server.py` 仅在 `_handle_initialize` 校验 token；`_handle_tools_call` 既不校验 token
也不校验 `_initialized`。

**影响**：任何能连上 MCP 通道的进程均可调用 `shell_exec` / `python_exec`，OS 级命令执行。

**建议**：在所有非 `initialize` 方法前置 token + 会话态校验；`run_tcp` 默认仅绑 `127.0.0.1`。

---

### R-03 🔴 RBAC 主体身份取自请求体，可冒充管理员

**证据**
```
api/routers/tasks.py           context: dict[str, Any]   ← 客户端可控
runtime/orchestrator.py:397    actor = request.context.get("actor", "anonymous")
runtime/orchestrator.py:398    LayerContext(..., user_id=actor)
security/rbac.py:273-276       if not self._admin_users: return True   ← 默认放行
```

**影响**：调用方自报 `context.actor = <admin 用户>` 即被采信；叠加默认全放行
与 `--host 0.0.0.0`，等价于未认证远程命令执行。

**建议**：身份必须由 API Key 凭证派生；RBAC 改 deny-by-default；默认绑定回环地址。

---

### R-04 🔴 模板路由正则无词边界，误判为 CS 射击任务

**证据**（复核脚本）
```
补充 docs 文档        -> cs_shooter
导出 metrics 指标     -> cs_shooter
写 statistics 模块    -> cs_shooter
优化 fps 到 60        -> cs_shooter
```
`TaskTemplateSelector.CS_RE = r"(?i)(cs|shooter|射击|fps|第一人称|counter.?strike)"`，
裸 `cs` 子串命中 `docs/metrics/statistics/specs`，`fps` 命中帧率语义。

**影响**：非游戏任务会拿到"CS 射击游戏的 29 文件空壳工程"。

**建议**：加词边界 `\b`，并优先使用 ITD frontmatter 的 `type`/`tags` 而非自然语言子串。

---

## 2. P1 — 显著影响正确性/成本/治理

### R-05 🟠 cs_shooter 模板只产出 placeholder 空壳

**证据**
```
cs_shooter: files=29  chars=4953  placeholder=7   dispatch=0.1ms
  shooter_server/src/main.rs → fn main(){ println!("shooter server placeholder"); }
  frontend/src/App.tsx       → <div>CS Shooter (placeholder)</div>
```
**影响**：通了模板但"没有真正生成代码"；29 个文件平均 171 字符。
**已缓解**：本次新增 `logic_gate` 会在交付前拦截此类空壳（blocking）。
**建议**：模板只定"文件清单+骨架"，内容交由 LLM 生成并过闸门。

### R-06 🟠 任务级缓存按 query 哈希跨主体复用

**证据**（复核脚本，三个请求同一 query）
```
第1次 (actor=cache-probe)   120.05s  tokens=0     status=failed
第2次 (actor=cache-probe)    16.75s  tokens=5643  status=success
第3次 (actor=other-tenant)    0.03s  tokens=0     status=success   ← 直接命中他人缓存
```
**影响**：① 不同主体共享结果（数据越权）；② 无法对同一需求重新生成；
③ 缓存命中分支位于 ZEN/policy 检查之前（治理被短路）。
**建议**：缓存键纳入 `actor` + 影响执行的 context；代码类任务默认关闭或极短 TTL；
把 `policy.check()` 提到缓存查询之前。

### R-07 🟠 子任务无调度器 — ✅ 已修复（2026-10-04 批次2）

> 修复内容见 `HARDENING_BATCH_2026-10-04.md` §4：REQ 子任务真实派发 +
> 需求级核验（覆盖率/证据/缺失项）+ 父任务门控 + status 端点暴露子任务。


**证据**
```
task_deca0a6e4600            completed  100%
task_deca0a6e4600-REQ-001    pending      0%
…（8 个 REQ 子任务全部 pending=8）
```
**影响**：ITD 导入产生的需求子任务从未被执行，"全流程完成"名不副实。
**建议**：父任务 execute 时按 REQ 拓扑派发子任务并汇总；未完成不得标记 completed。

### R-08 🟠 best-of-k 串行执行 — 🟡 已实现并行能力（2026-10-04 批次2）

> 详见 `HARDENING_BATCH_2026-10-04.md` §5：并行机制已落地并有 9 项单测；
> 但 3+3 轮实测显示本地单实例后端并发无收益（中位 7.0s vs 7.0s），
> 故默认串行，`candidates_parallel=True` 显式开启。


**证据**：`_select_best_candidate()` 内 `for _ in range(k): await self._do_generate(...)`；
实测 k=1→k=2 的 token 放大 2.89–3.14×，墙钟时间近似线性。
**建议**：`asyncio.gather` 并发 k 路生成（多样性由采样温度保证），并设 token 预算熔断。

### R-09 🟠 默认不强制断言，"不报错即通过"

**证据**：控制器 checks 实测 `{"sandbox": true, "assertions": false, ...}`，
`assertions_required` 默认 false；平台自报 pass 但功能正确率仅 25%（前次基准）。
**建议**：把"验收断言必须通过"设为代码类任务默认策略（`assertions_required=True`）。

### R-10 🟠 沙箱不是安全边界 — ✅ 已加固（2026-10-04 批次2）

> 详见 `HARDENING_BATCH_2026-10-04.md` §6：AST 危险调用判定、全 argv 命令检查、
> 路径穿越/敏感路径拦截、默认 cwd 从白名单派生、危险环境变量净化、
> `MORE_SANDBOX_LEVEL=strict` 额外强制导入白名单。
> 诚实标注：macOS 上仍是子进程沙箱，未做内核级隔离。

**证据**：`sandbox/policy.py::scan_python` 为子串匹配；`secure_sandbox._check_command`
只看第一个 token；macOS 上 `SubprocessSandbox` 无隔离；未传 `cwd` 时 `allowed_paths` 不生效。
可绕过形态：`getattr(__import__("os"),"system")(...)`、`base64 -d | sh`、`env LD_PRELOAD=...`。
**建议**：改用内核级隔离（容器/gVisor/WASM）+ AST 白名单 + 强制默认 cwd。

---

## 3. P2 — 可观测性与可维护性

### R-11 🟡 超时/取消的 LLM 调用不产生遥测
**证据**：`timeout_s=120` 的请求在 120.05s 返回 `failed`、`tokens=0`，遥测表无新增行
（记录只发生在调用**完成**时，`asyncio.wait_for` 超时路径未补记）。
**影响**：超时类故障在指标里表现为"没有调用"，掩盖真实失败量。
**建议**：在 `asyncio.TimeoutError` / `CancelledError` 分支补 `_emit_llm_call(success=False)`。

### R-12 🟡 执行工作目录被执行完的 `finally` 删除
**证据**：`api/routers/tasks.py` 末尾 `_shutil.rmtree(project_root)`；
交付包中 `TEST_REPORT.md` 仍引用已不存在的 `run_task_*` 路径。
**建议**：保留 N 天或按需归档，至少保留 manifest 与校验摘要。

### R-13 🟡 TEST_REPORT 内存峰值单位错误
**证据**：报告 `内存峰值: 2210922496.0 MB`（≈2.2 PB）。
**建议**：除以 1024² 换算为 GB，并补系统内存而非进程峰值。

### R-14 🟡 L0 重复裁决 + convergence 噪声
**证据**：`l0_execution.py` 在约 505 行与 586 行重复调用同一 `adjudicate_codegen`；
`is_prime` 这类平凡任务也报 `state=oscillating, divergence_detected=true`（完整性恒 0.5）。
**建议**：去重；completeness 改为可区分指标。

### R-15 🟡 前端未接入真实遥测且无鉴权头 — ✅ 已修复（2026-10-04 批次2）

> 详见 `HARDENING_BATCH_2026-10-04.md` §7：新增统一 `apiClient`（16 处 fetch 全部收口、
> 自动注入 Bearer）、Home 页新增运行时遥测面板（token/延迟/成功率/交付成功率，
> 支持 1h/6h/24h 窗口），并修复 **CORS 默认值被 .env 覆盖** 与 **缓存命中污染延迟分位** 两个真实缺陷。

**证据**：`app/src/core/moreEngine.ts:642-645` 的 `fetch()` 未带 `Authorization`；
启用 `MORE_API_KEY` 后这些调用返回 401；`Home.tsx` 的吞吐/延迟卡片来自本地状态而非遥测。
**建议**：统一 API 客户端注入 Key，并把 `/api/v1/metrics/llm` 接入首页卡片。

---

## 4. P3 — 体验与工程卫生

### R-16 🟡 用户可见路径 `/health` 返回 404
**证据**：`GET /health -> 404`，正确为 `GET /api/v1/health`（浏览器当前正停在该 404 页）。
**建议**：加 301/307 跳转或根路径说明页。

### R-17 🟡 脱敏权衡：≤14 字符无引号密钥不再脱敏
**证据**：`Set PASSWORD=my_super_secret in env`（14 字符）不再命中；
`PASSWORD=my_super_secret_value_123`（≥16）仍命中。
**说明**：这是为"不破坏生成代码"做的**有意取舍**（旧规则会吃掉 `key=lambda`）。
**建议**：如需覆盖短密钥，按"是否位于代码块内"分流处理。

### R-18 🟡 未提交改动与历史 lint 债务
**证据**：工作区长期存在 100+ 项未提交改动；全仓 `ruff check` 仍有约 80 条历史告警
（新增文件均为 clean）。
**建议**：按主题拆分提交；逐步清零 lint 后去掉 CI 的 `|| true`。

### R-19 🟡 环境限制
**证据**：`make` 触发 Xcode 许可提示而不可用（`make health` 已修但本机无法验证）；
`./run-local-ai.sh start` 会自动拉起 27B llama.cpp 并 OOM，连带杀死 API。
**建议**：更新 Xcode 许可；把大模型启动改为显式 opt-in。

---

## 5. 复核命令（可复现）

```bash
# R-01
git check-ignore -v app/src/lib/utils.ts && git ls-files app/src/lib | wc -l

# R-02  MCP 认证绕过
MORE_MCP_KEY=supersecret .venv/bin/python -c "
import asyncio,json,sys; sys.path.insert(0,'more_core')
from more_core.mcp.server import MCPServer
from more_core.mcp.protocol import ToolCallResult
async def m():
    s=MCPServer()
    async def d(a): return ToolCallResult(content=[{'type':'text','text':'EXECUTED'}])
    s.register_tool('shell_exec','x',{'type':'object'},d)
    print(await s._handler.handle_message(json.dumps({'jsonrpc':'2.0','id':1,
          'method':'tools/call','params':{'name':'shell_exec','arguments':{}}})))
asyncio.run(m())"

# R-04  模板路由误判
.venv/bin/python -c "
import sys; sys.path.insert(0,'more_core')
from more_core.core.native_executor.planner import TaskTemplateSelector as T
from types import SimpleNamespace as S
print(T().key_for(S(query='补充 docs 文档'), None))"     # -> cs_shooter

# R-06  缓存跨主体复用：同一 query 连发 3 次，第 3 次换 actor 观察 0 秒命中

# R-07  子任务状态
.venv/bin/python -c "
import sqlite3; c=sqlite3.connect('more_core/data/tasks.db')
print(c.execute(\"SELECT status,COUNT(*) FROM tasks WHERE task_id LIKE 'task_deca0a6e4600%' GROUP BY status\").fetchall())"
```

---

*复核人: Codex · 2026-10-04 · 每条均标注可复现证据*
