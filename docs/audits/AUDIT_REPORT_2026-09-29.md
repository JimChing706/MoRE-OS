# QNMing MoRE OS — 综合审计报告

**审计日期**: 2026-09-29
**审计版本**: v0.9.9（`more_core/more_core/version.py`）
**审计对象**: 工作区 `qnm-os-prev-202605211332` @ `main`（HEAD `4472900`）+ 106 项未提交改动
**审计方法**: 全量代码走读 + 静态门禁重跑 + 针对性 PoC 复现 + 历史审计回归比对
**上轮基线**: `docs/AUDIT_REPORT_2026-08-04-followup.md`（当时结论：全绿、无 P1/P2 未决）

---

## 0. 审计范围与运行时

| 项目 | 数值 |
|------|------|
| 后端源文件 | 196 个 `.py`（`more_core/more_core/`），42,067 行 |
| 后端测试 | 70 个 `test_*.py`（`more_core/tests/`），16,631 行 |
| 前端 | React 19 + Vite 7 + TS 5.9（`app/src/`） |
| 运行时 | Python 3.14.3 · `.venv/`（仓库根）· FastAPI · pydantic 2.13 |
| 未提交改动 | 106 项（47 个已修改文件 + 59 项未跟踪，约 +5,060 / −2,272 行） |

审计覆盖：API 路由层、L0–L5 执行链、LLM 管理、沙箱与安全、治理/审计、MCP/A2A 协议、
持久化与缓存、前端构建链、测试与 CI、依赖与仓库卫生。

---

## 1. 审计摘要

| 维度 | 状态 | 实测结果 |
|------|:----:|----------|
| 后端测试 | ❌ | **1105 passed / 12 failed**（全部 401，本地 `.env` 依赖） |
| 后端覆盖率 | ⚠️ | **70%**（17,812 stmt / 5,402 miss），较上轮 65% 提升 |
| Ruff lint | ❌ | **85 errors**（F401×41、E701×21、F841×7、E402×7、F811×4、**F821×3**） |
| Ruff format | ❌ | **84 个文件**需重排 |
| Mypy（strict） | ❌ | **36 errors / 12 文件**（CI 用 `|| true` 屏蔽） |
| 前端 tsc | ✅ | `tsc -b --noEmit` 0 error |
| 前端 ESLint | ❌ | **26 errors**（麻将组件 25 + socket hook 1） |
| 前端 Vitest | ✅ | 5 文件 / 38 用例通过 |
| 前端构建 | ✅ | `vite build` 成功（gzip 约 61.7 kB 主包 + 分包） |
| 密钥泄漏 | ⚠️ | 无真实密钥入库；`docs/API_KEY.md` 含可被误用的"真实格式"示例键 |
| 仓库卫生 | ❌ | 71 MB 压缩包、嵌套全量工作树副本、`MagicMock/` 垃圾目录 |
| CI 可绿 | ❌ | lint / format / eslint 三道硬门禁当前全部会红 |

**总体结论**: 相对 2026-08-04 的"全绿基线"出现**全面质量回归**。根因是一批未提交的
"白龙马融合 / ITD 原生执行 / Provenance / API-Key 运维"改动直接堆在工作区 `main` 上，
绕过了 lint、format、eslint 与部分测试。其中最严重的一类是**治理与安全机制看似存在、
实测可绕过或根本不生效**（`_prov` 溯源静默失败、MCP 认证可绕过、RBAC 身份可伪造、
缓存短路治理）。

---

## 2. 质量门禁回归对比

| 门禁 | 2026-08-04 基线 | 2026-09-29 实测 | 变化 |
|------|:---:|:---:|:---:|
| pytest | 735 / 735 通过 | 1105 / 1117 通过 | 🔴 12 失败 |
| Ruff check | 0 error | 85 error | 🔴 |
| Ruff format | 通过 | 84 文件需重排 | 🔴 |
| Mypy | 0 error | 36 error | 🔴 |
| ESLint | 0 error | 26 error | 🔴 |
| 覆盖率 | 65% | 70% | 🟢 |

> 覆盖率提升来自新增测试；但新增代码同时引入了失败用例与静态错误，"测试变多"并不等于"质量变好"。

---

## 3. 严重发现（P0 — 发布阻断）

### AUD-01 🔴 前端核心源码被 `.gitignore` 误伤，新克隆无法构建

**证据**
```
.gitignore:18                     lib/                 ← 源自 Python 打包模板
git check-ignore -v app/src/lib/utils.ts
  → .gitignore:18:lib/  app/src/lib/utils.ts
git ls-files app/src/lib          → 0 个文件（整目录未入库）
grep -rl '@/lib/utils' app/src    → 15 个文件
grep -rl '@/lib/format' app/src   → 7 个文件
```

`app/src/lib/` 下有 `utils.ts`（shadcn `cn()` 助手）、`format.ts`、`format.test.ts`。
该目录被仓库根 `.gitignore` 的 `lib/` 规则整体忽略，**从未提交**。

**影响**: 任何一次 `git clone` / CI checkout 得到的前端都缺少 `@/lib/utils`，
`npm run build`、`npx tsc -b`、`npm test` 全部失败；而本地因为文件存在而"看起来正常"。
这是最典型的"本地绿、远端红"陷阱。

**修复**: 将 `.gitignore:18` 的 `lib/` 改为仅匹配构建产物（如 `/lib/`、`more_core/lib/`），
`git add -f app/src/lib/` 并补齐 `app/src/lib/*` 到版本库。

---

### AUD-02 🔴 交付物与仓库状态脱节：59 项未跟踪、~5,000 行新代码不在 Git 中

**证据**
```
git status --short | wc -l        → 106
git status --short | grep '^??'   → 59（untracked）
git diff --stat | tail -1         → 47 files changed, 5060 insertions(+), 2272 deletions(-)
```
未跟踪项包括整块新子系统与全部对应测试：
`more_core/more_core/core/native_executor/`（3,006 行）、`core/guardrails/`、
`governance/observability.py`、`security/api_key_ops.py`、`api/routers/admin_api_key.py`、
`codegen/controller.py`、`codegen/evolution_signal.py`、`a2a/bailongma_bridge.py`，
以及 18 个新增测试文件、根级 `tests/`、`deliverables/`、`docs/API_KEY.md`。

**影响**: CI 只会跑 `main` 上已提交的代码，上述全部能力既不会被构建、也不会被测试；
`RETROSPECTIVE_REPORT.md` 声称的"闭环交付"无法由版本库状态佐证。同时 `main` 上挂着
一份长期未提交的大规模改动，使 review、回滚与二分定位全部失效。

**修复**: 按主题拆分为若干 Conventional Commits（例如 `feat(native-executor)`、
`feat(guardrails)`、`feat(api-key)`、`test(...)`），先恢复 lint/format/test 绿，再逐个提交。

---

### AUD-03 🔴 三道 CI 硬门禁当前全部会红

**证据**
```
python -m ruff check more_core/ tests/      → Found 85 errors
python -m ruff format --check ...           → 84 files would be reformatted
cd app && npx eslint .                      → 26 problems (26 errors)
python -m pytest tests/                     → 12 failed, 1105 passed
```
`.github/workflows/ci.yml` 中 ruff check、ruff format --check、eslint 均为**硬门禁**（无 `|| true`），
因此当前 `main` 推上去 CI 必红。

**失败测试清单**: `test_a2a_http_p3.py`（10 项）、`test_evolution_summary_panel.py`（2 项），
全部为 `assert 401 == 200`。

---

## 4. 高危发现（P1 — 安全）

### AUD-04 🔴 MCP Server 认证可被直接绕过（已复现）

**证据**（`more_core/more_core/mcp/server.py`）
```
:157  _handle_initialize  → 校验 MORE_MCP_KEY / MORE_API_KEY
:196  _handle_tools_call  → 无任何 token / _initialized 校验
:278  protocol.handle_message → 仅按 method 分派，不检查会话状态
```

PoC（设置 `MORE_MCP_KEY=supersecret` 后）:
```
no-auth tools/call -> {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text",
                      "text":"TOOL EXECUTED: {\"command\": \"id\"}"}],"isError":false}}
bad init            -> {"error":{"code":-32603,"message":"Unauthorized: invalid MCP token"}}
```
未发 `initialize`、未带 token 的 `tools/call` 被正常执行。

**影响**: 任何能连上 MCP TCP/stdio 通道的进程可调用 `shell_exec`、`python_exec` 等工具，
鉴权形同虚设。上轮审计 SEC-02 被标记为"已修复"，实际只修了握手环节。

**修复**: 在 `_handle_tools_call`（以及所有非 `initialize` 方法）前置 `self._initialized`
与 token 校验；TCP 场景改为每连接会话状态；默认 `run_tcp` 仅绑 `127.0.0.1`。

---

### AUD-05 🔴 RBAC 主体身份由客户端请求体决定，可冒充管理员

**证据**
```
api/routers/tasks.py:26        context: dict[str, Any]        ← 客户端完全可控
runtime/orchestrator.py:397    actor = request.context.get("actor", "anonymous")
runtime/orchestrator.py:398    ctx = LayerContext(core=self, request=request, user_id=actor)
runtime/orchestrator.py:1005   context = dict(body["context"])   ← A2A 远端注入
security/rbac.py:273-276       if not self._admin_users: return True   ← 默认放行
```

**影响**: 两条独立问题叠加。
1. 执行身份取自请求体 `context.actor`，与 API Key 无绑定，调用方自报"我是 admin"即被采信；
2. `UnifiedRBAC` 在未配置 `admin_users` 时对任何 `user_id` 一律放行，而 `shell_exec` /
   `python_exec` 的 `required_permission` 正是走这条 `check()`。

再叠加 `make start` / `cli serve` 默认 `--host 0.0.0.0`（Makefile:51、cli.py:283）且
`MORE_API_KEY` 未设置时 API 完全不鉴权，**默认开发配置等价于局域网可达的未认证 RCE**。

**修复**: 身份必须来自认证凭证（API Key → 主体映射），禁止从 body/context 读取 actor；
RBAC 默认改为 deny-by-default；服务默认绑定 `127.0.0.1`，显式 `--host 0.0.0.0` 时强制要求 API Key。

---

### AUD-06 🔴 API-Key 轮换端点：`rotation_proof` 可省略 + 任意绝对路径写盘 + 功能名不副实

**证据**（`more_core/more_core/api/routers/admin_api_key.py`）
```
:111  if payload.rotation_proof:  verify_rotation_proof(...)
:122  else:  warnings.append("no rotation_proof supplied — ... testing only")
:101  if payload.write_env_file:  (允许任意绝对路径)
:109  inject_api_key_into_env(new_key, payload.write_env_file, backup=True, ...)
```
`inject_api_key_into_env` 实测对任意绝对路径可写并 `chmod 0600`：
```
written to: /private/tmp/audit_arbitrary_write_demo
# qnming MoRE OS .env — generated by `more-os api-key inject`
MORE_API_KEY="sk-more-os-AAAA..."
```
另外：全仓库无任何 `os.environ["MORE_API_KEY"] = ...`，`revoke_old_in_seconds` 只出现在
响应/provenance 里，**旧 key 不会被吊销、运行中的进程不会换 key**。而 `_require_api_key`
每次请求现读 `os.getenv`，即便写了 `.env` 也要重启才生效。

**影响**: 该端点被真实挂载进 `create_app`（生产路径），构成：
(a) 免 proof 的越权调用面；(b) 任意路径追加写 + `chmod 600` 原语；
(c) 返回 `status: rotated` 的假成功，误导运维以为完成了热轮换。

**修复**: 移除 `rotation_proof` 可选项（缺失即 403）；`write_env_file` 限制在配置白名单目录内；
真正实现 key 热替换与旧 key 过期（或直接删除该端点，改为 out-of-band 轮换）。

---

### AUD-07 🔴 Python 沙箱不是安全边界，黑名单可平凡绕过

**证据**
```
sandbox/secure_sandbox.py:139   _check_command → 仅取 full_cmd.split()[0] 比对黑名单
sandbox/secure_sandbox.py:187   _check_path(None) → 直接 return True, ""
sandbox/secure_sandbox.py:160   _check_python_code → default_policy().scan_python(code)
sandbox/policy.py:92            scan_python → 纯 substring 匹配（"os.system" in code）
sandbox/subprocess_sandbox.py   macOS 上即普通 create_subprocess_exec（无隔离）
```

可直接绕过的形态（静态扫描全部放行）：
- `getattr(__import__("os"), "system")("...")` —— 无 `os.system` 字面量
- `import importlib; importlib.import_module("subprocess").run(...)`
- `import \` 换行 `subprocess` —— `validate_imports` 只按行首 `import ` 匹配
- 任何命令（`sh -lc`、`base64 -d | sh`、`env LD_PRELOAD=...`） —— 黑名单只看第一个 token
- 未显式传 `cwd` 时 `allowed_paths` 完全不生效；`startswith(realpath(ap))` 还存在
  `/tmp` 前缀误匹配 `/tmpfoo` 的问题

**影响**: 系统对外宣称"沙箱隔离 + 16 层安全防护"，实际在 macOS 开发环境
（`SecurityLevel.BASIC`，`bootstrap.py:57`）下只是"带超时的子进程"。任何进入
`python_exec` 的 LLM 生成代码都能读写整个文件系统、发起网络请求。

**修复**: 默认 `SECURITY_LEVEL=STRICT` 且改用真正的内核级隔离（容器/gVisor/WASM）；
静态扫描改为 AST 白名单（项目内 `workflows/engine.py:186` 已有可复用的 `_ALLOWED_AST_NODE_TYPES` 模式）；
修正 `_check_path` 的前缀比较（`Path.is_relative_to`）并强制对 `run()` 施加默认 cwd。

---

## 5. 高危发现（P1 — 正确性 / 治理失效）

### AUD-08 🔴 `_prov` 未定义 → 外部执行溯源戳静默失效（打脸验收结论）

**证据**
```
api/routers/tasks.py:358   from ...guardrails.provenance_audit import get_default_layer as _get_prov
api/routers/tasks.py:376   _prov().mark(str(task_id), "external_tool_chain", ...)   ← NameError
api/routers/tasks.py:461   _prov().mark(str(task_id), "external_tool_chain", ...)   ← NameError
ruff: F821 Undefined name `_prov`（×2）
```
两处调用分别包在 `try: ... except Exception: pass` 中，因此 `NameError` 被**完全吞掉**。

**影响**: `RETROSPECTIVE_REPORT.md` 把"外部 HTTP execute 路由必打 `external_tool_chain` 源戳"
列为整改成果与 AC 通过依据；实际上该源戳**一次都不会写入**。这正是项目自订原则 12
"失败要大声暴露"被违反的样例——静默 `except: pass` 让治理机制永久性假阳性。

**修复**: 把 `_prov` 改为 `_get_prov()`；把 `except Exception: pass` 至少改为
`except Exception: _log.warning(..., exc_info=True)`；为两条路由补一条"缺少溯源记录即失败"的测试。

---

### AUD-09 🟠 任务级结果缓存短路治理与租户隔离

**证据**
```
runtime/orchestrator.py:342  cache_key = f"{request.type.value}|{sha256(request.query)}"
runtime/orchestrator.py:343  cached = await self._request_cache.get(cache_key, "task")
runtime/orchestrator.py:344-351 命中即返回 status=SUCCESS
runtime/orchestrator.py:457  self.policy.check(request)     ← 在缓存命中之后才执行
runtime/orchestrator.py:430  ZEN-19 拒绝检查               ← 同样在之后
```
缓存键只含 `task_type + query`，不含 `actor`、`context`、`plugin_type`、`target_layer`、
`allow_self_improvement` 等任何请求参数；默认 TTL 3600s、容量 1000。

**影响**:
- 同一 query 文本跨用户/跨租户复用同一份输出（数据越权与串味）；
- 命中缓存直接返回 `SUCCESS`，跳过 ZEN 规则、`PolicyEnforcer`、taint 校验；
  一条此前被允许的 query 可以让后续本应被拒绝的同类请求"搭车"成功。

**修复**: 缓存键纳入主体与影响执行的上下文（至少 `actor` + 影响路由的字段）；
把 `policy.check` / ZEN 前置到缓存查询之前，或对命中结果重新走治理校验。

---

## 6. 中危发现（P2）

### AUD-10 🟠 测试非隔离：依赖本地 `.env`，并在磁盘上生成数百个垃圾目录

**证据 A — 12 个 401 失败**
```
more_core/.env:53      MORE_API_KEY=sk-more-o…（真实开发 key）
more_core/tests/conftest.py  → 未设置/清理 MORE_API_KEY
tests/test_a2a_http_p3.py    → 请求不带 Authorization 头
结果：assert 401 == 200（10+2 项）
```
`.env` 通过 `core/config._load_dotenv()` 自动加载，于是"是否鉴权"取决于开发者本机配置。
CI 上没有 `.env`，这些用例反而会绿——即**本地红、CI 绿**，同样不可信。

**证据 B — `MagicMock/` 垃圾目录**
```
more_core/MagicMock/mock.settings.project_root/   323 个以 mock id 命名的子目录
  └── 4582928272/more_core/data/codegen_evolution.db
```
`Path(MagicMock())` 会被 pathlib 解析成 `MagicMock/mock.project_root/<id>`；
`codegen/evolution_signal.py:145-153` 的 `_resolve_db_path` → `_get_conn` 直接
`mkdir(parents=True)`，于是每次测试运行都在 CWD 下新建一批目录（本次审计运行后
目录数从 322 增至 323，mtime 与测试一致）。

**影响**: 测试结果不可复现；工作区被持续污染；`Path` 参数缺少类型/存在性防御。

**修复**: conftest 里 `monkeypatch.delenv("MORE_API_KEY")` 或显式注入测试 key；
`_resolve_db_path` 校验 `project_root` 为 `str | os.PathLike` 且存在；
测试统一用 `tmp_path` 并设置 `MORE_CODEGEN_EVOLUTION_DB`。

---

### AUD-11 🟠 领域强耦合：`native_executor` 把"俄罗斯方块"写进了内核

**证据**
```
more_core/more_core/core/native_executor/
  writer.py                 1508 行（内含整套 Rust/HTML/CSS 模板字符串）
  delivery.py                783 行
  tetris_original_prompt.py  237 行
  planner.py                 220 行 → RULE_BASED_TETRIS_PLAN 固定 7 步计划
  validator.py               237 行
native_executor/ 内 tetris/mahjong 提及：49 处
```
`tasks.py:113-118` 的失败兜底直接 `deepcopy(RULE_BASED_TETRIS_PLAN)`。

**影响**: 违反项目自订原则 G1"领域无关内核 + 行业插件壳 / Core 零领域耦合"。
`RETROSPECTIVE_REPORT.md` 用"俄罗斯方块 100% 原生执行"证明通用能力，但实现是**针对单一
demo 的硬编码模板**，无法推广到麻将/CS 等其它交付物；同时 3,000 行模板代码拉低可维护性与覆盖率质量。

**修复**: 将 `native_executor` 中的领域内容整体迁移到 `plugins/`（作为 Industry Pack）；
内核只保留"LLM 规划 → 白名单写盘 → 验证 → 打包"的领域无关骨架与接口。

---

### AUD-12 🟠 根级 `tests/` 3 个文件 6 个用例从未被 CI 执行

**证据**
```
tests/test_e2e_native_tetris_itd_flow.py     (1)
tests/test_longterm_provenance_guards.py     (3)
tests/test_tetris_native_fixture.py          (2)
git ls-files tests        → 0（未跟踪）
pyproject testpaths       → ["tests"]，相对 more_core/ ⇒ 只收集 more_core/tests
显式运行：6 passed
```
**影响**: 覆盖"ITD 原生流程 / 长期溯源守卫"的关键回归用例不存在于版本库，也不会被
`make test` 或 CI 收集；一旦删除或搞坏同样无人发现。

**修复**: 迁入 `more_core/tests/`（或把根 `tests/` 纳入 testpaths），并确认与
`more_core/tests/test_native_*.py` 无重复。

---

### AUD-13 🟠 Mypy 软门禁掩盖 36 个真实类型错误

**证据**
```
CI: run: python -m mypy more_core/ || true       ← 永不失败
Makefile:126  mypy more_core/ || true            ← 同样屏蔽
实测: Found 36 errors in 12 files（strict）
```
代表性错误：
- `llm/task_router.py:66,91,129,151,193` —— `dict | None` 直接 `.get()`（潜在 None 解引用）
- `runtime/orchestrator.py:1101,1144` —— `"TaskResult" has no attribute "data"`
- `layers/l0_execution.py:1320` —— `A2ATaskState` 未显式导出
- `api/routers/tasks.py:376,461` —— 即 AUD-08 的 `_prov`（mypy 与 ruff 双报）

**影响**: `pyproject.toml` 声明 `strict = true`，但门禁被 `|| true` 抵消，
"strict" 是装饰性的。类型错误中至少两类同时具备运行时风险。

**修复**: 分批归零 mypy，再摘除 `|| true`；先修 `_prov`、`task_router` 的 `None` 解引用。

---

## 7. 低危 / 卫生问题（P3）

| ID | 问题 | 证据 |
|----|------|------|
| AUD-14 | 版本漂移 | `version.py=0.9.9`；`CHANGELOG.md` 顶层仍是 `[0.8.0] 2026-05-21`；`Makefile:4` 注释 `Version: 0.8.0`；`mcp/server.py:64` 硬编码 `"0.3.0"` |
| AUD-15 | 文档与实现不一致 | README:131-132 写 `POST /a2a`、`GET /a2a/agent-card`，实际路由前缀 `api/v1`（`routers/a2a.py:18,23,32,46`）；`CLAUDE.md` 的 `cd more_core && .venv/bin/python` 路径不存在（venv 在仓库根） |
| AUD-16 | 仓库体积与残留 | 根目录 `mahjong_suite_v2-*.zip/.tar.gz` 各约 71 MB；`.kilo/worktrees/panoramic-swamp/`（5.2 MB 全量副本）；`MagicMock/`、`more_core/MagicMock/`；`bailongma_chassis/` 342 MB |
| AUD-17 | 示例密钥可被误用 | `docs/API_KEY.md:70` `MORE_API_KEY=sk-more-os-3Qm9…S5g`（此处已脱敏）是格式合法、可直接复制启用的"真实形态"示例 |
| AUD-18 | 关键模块低覆盖 | `router/scene_router.py` 0%、`mcp/client.py` 22%、`llm/providers/openai_compat.py` 21%、`skills/code_skills.py` 21%、各 `channels/*_adapter.py` 27–31%、`mcp/server.py` 46% |

> AUD-18 与 AUD-04 直接相关：MCP Server 覆盖率不足正是认证绕过未被测试捕获的原因。

---

## 8. 历史审计项回归检查

| 上轮项 | 上轮结论 | 本次复核 |
|--------|:--------:|----------|
| SEC-01 RBAC 未接入执行管道 | 已修（工具级 `required_permission`） | ⚠️ 部分修复：工具级检查存在，但主体身份来自客户端 `context.actor`（AUD-05） |
| SEC-02 MCP Server 零认证 | 已修（`initialize` 校验 token） | ❌ **回归/修复不完整**：`tools/call` 仍无鉴权（AUD-04，已 PoC 复现） |
| SEC-03 A2A 端点零认证 | 已修（`require_api_key` + `TASK_EXECUTE`） | ⚠️ 端点级已加依赖，但身份仍可由请求体控制（AUD-05） |
| SEC-06 SecureSandbox blocked_commands 绕过 | 标记未修 | ❌ 仍未修，且新增 `scan_python` 也是子串匹配（AUD-07） |
| GOV 外部执行源戳 | 整改后"必打 `external_tool_chain`" | ❌ **实际不生效**（AUD-08） |
| CI mypy 不阻断 | 已知问题 | ❌ 仍存在，另有 ruff/eslint 硬门禁转红（AUD-03/AUD-13） |

---

## 9. 建议修复路线图

**第 0 批（阻断发布，当天）**
1. AUD-01 修 `.gitignore` 并提交 `app/src/lib/`；本地删除后重跑 `npm ci && npm run build` 验证。
2. AUD-08 修 `_prov` → `_get_prov()`，并补溯源断言测试。
3. AUD-02 把 59 项未跟踪改动按主题拆分提交（先保证工作区可回滚）。

**第 1 批（安全，1 周内）**
4. AUD-04 MCP 全方法鉴权 + TCP 默认回环绑定。
5. AUD-05 身份改为凭证派生；RBAC deny-by-default；默认 host 改 127.0.0.1。
6. AUD-06 删除或收紧 api-key rotate（proof 必填 + 路径白名单 + 真正轮换）。
7. AUD-09 缓存键纳入主体/上下文，治理检查前置。

**第 2 批（质量门禁，2 周内）**
8. AUD-03/AUD-13 归零 ruff / format / eslint / mypy，再摘除 `|| true`。
9. AUD-10 测试隔离（`delenv MORE_API_KEY`、`tmp_path`、`MORE_CODEGEN_EVOLUTION_DB`）。
10. AUD-12 根 `tests/` 迁入 `more_core/tests/`。

**第 3 批（架构与卫生）**
11. AUD-11 `native_executor` 领域内容下沉到 `plugins/`。
12. AUD-07 沙箱升级为真实隔离 + AST 白名单。
13. AUD-14~17 版本对齐、文档纠正、清理大文件与残留目录、示例键改为占位符。

---

## 10. 附录 A — 复现命令

```bash
# 测试基线
cd more_core && ../.venv/bin/python -m pytest tests/ -q
#   → 12 failed, 1105 passed

# 覆盖率
cd more_core && ../.venv/bin/python -m pytest tests/ -q --cov=more_core
../.venv/bin/python -m coverage report | grep TOTAL      # → 70%

# 静态门禁
cd more_core && ../.venv/bin/python -m ruff check more_core/ tests/          # 85 errors
cd more_core && ../.venv/bin/python -m ruff format --check more_core/ tests/ # 84 files
cd more_core && ../.venv/bin/python -m mypy more_core/                       # 36 errors
cd app && npx eslint .                                                       # 26 errors

# AUD-01：前端源码未入库
git check-ignore -v app/src/lib/utils.ts
git ls-files app/src/lib | wc -l        # → 0

# AUD-04：MCP 认证绕过
MORE_MCP_KEY=supersecret .venv/bin/python - <<'PY'
import asyncio, json
from more_core.mcp.server import MCPServer
from more_core.mcp.protocol import ToolCallResult
async def main():
    srv = MCPServer()
    async def danger(a):
        return ToolCallResult(content=[{"type":"text","text":"TOOL EXECUTED"}])
    srv.register_tool("shell_exec","d",{"type":"object"},danger)
    req={"jsonrpc":"2.0","id":1,"method":"tools/call",
         "params":{"name":"shell_exec","arguments":{"command":"id"}}}
    print(await srv._handler.handle_message(json.dumps(req)))
asyncio.run(main())
PY

# AUD-10：垃圾目录随测试增长
ls more_core/MagicMock/mock.settings.project_root | wc -l
```

## 11. 附录 B — 已确认的正向项

- `app/src/` 与后端 SQL 全部使用参数化查询，未见 SQL 注入点（`evolution_signal.py:213` 的
  `f"ALTER TABLE ... {col} {ddl}"` 来源为文件内常量表，非用户输入）。
- `workflows/engine.py:186` 的 `_safe_eval_condition` 采用 AST 白名单 + 空 `__builtins__`，
  是本仓库唯一实现正确的表达式求值路径，可作为沙箱静态检查的改造范本。
- `native_executor/writer.py:186` 的 `_assert_safe_path` 具备"先全量校验、后写盘（0 写盘原则）"、
  `..` 拒绝与 `/tmp` 前缀白名单，方向正确。
- `governance/audit.py` 采用后台写线程 + JSONL + 11 项强类型合规字段，`read_recent` 前 flush，
  设计合理。
- `event_bus.py` 提供 `_pending_tasks` 上限告警、通配订阅与停机 drain。
- 前端 `tsc` 0 error、`vite build` 成功、Vitest 38/38 通过；后端覆盖率从上轮 65% 提升到 70%。
- 仓库未跟踪任何真实 `.env`、`.pem`、`.key` 或运行时数据库（`.gitignore` 生效）。

---

**报告结论**: 项目在产品叙事（治理、审计、沙箱、受控自进化）上领先，但本次审计证明
这些机制中有数项**要么可被平凡绕过、要么从未真正生效**（AUD-04/05/06/08/09），
且质量门禁已从"全绿"回退到"四红"。建议先执行第 0 批与第 1 批，
让"安全承诺"与"代码事实"重新对齐，再继续扩展能力面。

---

*审计人: Codex · 2026-09-29 · 方法: 全量走读 + 门禁重跑 + PoC 复现*
