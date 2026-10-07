# MORE_API_KEY 配置说明

QNMing MoRE OS HTTP API 的 Bearer-Token 认证密钥。本文件是该密钥的**唯一权威说明**；
`more_core/.env.template`、`more_core/.env.example` 中的注释只做速查并回链至此。

---

## 1. 作用范围

`MORE_API_KEY` 是一个**单一共享密钥**，没有按用户/租户细分，也没有多级权限。它的作用：

| 生效位置 | 行为 |
|----------|------|
| `api/server.py` `_require_api_key` | HTTP 依赖，校验 `Authorization: Bearer <key>`。挂载在**全部 22 个 router** 上。 |
| `api/routers/monitor.py` `ws_monitor` | WebSocket `/ws/monitor`，校验 `authorization` 头，不匹配则以 `4001` 关闭连接。 |
| `mcp/server.py` `_handle_initialize` | MCP 服务端，优先取 `MORE_MCP_KEY`，为空时回退 `MORE_API_KEY`。 |
| `mcp/client.py` | MCP 客户端，作为 `initialize` 的 `auth_token` 上送。 |
| `api/routers/security.py` `/security/status` | 仅用于展示 `active` / `dev_mode` 状态。 |

校验使用 `hmac.compare_digest`（常数时间比较），不区分大小写以外的任何格式。

### 权限范围

- **认证（Authentication），不是授权（Authorization）**：持有密钥即拥有全部 API 的全部权限。
  细粒度权限由独立的 RBAC 系统（`core.rbac`）控制，与本密钥无关。
- 密钥**不做吊销名单**。轮换即失效（见 §6）。
- 空白字符会被 `strip()`。配置值前后不要留空格。

### 不受本密钥保护的端点

以下路径由 FastAPI 应用层直接提供，**没有**挂 `_require_api_key`，即使配置了密钥也可匿名访问：

- `GET /api/docs`（Swagger UI）
- `GET /api/redoc`
- `GET /api/openapi.json`（完整 API schema）

它们只暴露接口结构，不返回业务数据。若生产环境需要收敛，限制反向代理的匿名访问范围。

---

## 2. 获取渠道

MoRE OS **不签发** `MORE_API_KEY`——它是自服务生成的共享密钥，不来自任何外部 CA 或密钥服务。

```bash
# 方式 A：标准库生成（推荐，无额外依赖）
python -c "import secrets; print('sk-more-os-' + secrets.token_urlsafe(32))"

# 方式 B：OpenSSL
openssl rand -base64 32 | sed 's/+/-/g; s#/#_#g'
```

生成后请存入密码管理器，再写入本机 `more_core/.env`。**不要**贴进 issue、PR、聊天记录或
任何会被提交的文件。

---

## 3. 填写格式要求

| 要求 | 值 | 校验点 |
|------|-----|--------|
| 前缀 | `sk-more-os-` | 仅在严格模式下强制（`validate_api_key`） |
| 最小长度 | 16 字符（不含前缀） | 任何模式下都会告警；严格模式下拒绝启动 |
| 字符集 | URL-safe（`A-Za-z0-9-_`） | 由 `secrets.token_urlsafe` 保证，可安全放进 HTTP 头与 URL |
| 禁止 | 引号包裹、行内注释、空格 | dotenv 与 shell 双层解析会产生分歧 |

正确：

```
MORE_API_KEY=sk-more-os-REPLACE_WITH_YOUR_OWN_KEY   # 请用 `more-os api-key issue` 生成，勿照抄示例
```

错误：

```
MORE_API_KEY="sk-more-os-..."          # 引号会成为值的一部分
MORE_API_KEY=sk-more-os-xxx # comment  # 行内注释不被支持
MORE_API_KEY=sk-more-os-xxx           # 长度不足
```

---

## 4. 配置生效的前置条件

按顺序核对，缺任一条都会导致"密钥配了但没生效"：

1. **变量在进程启动前已存在。** `core/config.py:_load_dotenv()` 在**模块导入时**执行一次
   （`override=False`）。进程启动后再改 `.env` 不生效，必须重启。
2. **真实 shell 环境变量优先于 `.env`。** 若 CI / launchd / systemd 已注入同名变量，
   `.env` 中的值会被忽略。排查时先 `env | grep MORE_API_KEY`。
3. **`.env` 位置。** `_load_dotenv()` 从 `more_core/more_core/core/` 向上逐级查找，
   **命中第一个 `.env 即停止**。当前命中的是 `more_core/.env`。
   仓库根目录的 `.env` 不会被读取。
4. **默认 .env 单文件自动加载 + 可选多环境配置文件。** `_load_dotenv()` 默认
   只自动加载字面量 `.env`（从 `more_core/more_core/core/` 向上查找，命中第一个即停止）。
   已提供多环境配置文件：
   - `more_core/.env.development` — 开发（MORE_REQUIRE_API_KEY=0，允许缺省密钥跑开发模式）
   - `more_core/.env.production`  — 生产（MORE_REQUIRE_API_KEY=1，缺密钥直接拒绝启动）
   - `app/.env.development` / `app/.env.production` — Vite 前端多环境变量（Vite 自动按 NODE_ENV 读取）

   后端要使多环境文件生效，三选一（不要混用）：
   (A) 启动前 `cp more_core/.env.development more_core/.env` 或软链 `ln -s`；
   (B) 启动前 `set -a && . more_core/.env.development && set +a` 导出到当前 shell（优先级高于 .env）；
   (C) 进程管理器（systemd / launchd / docker-compose）以 `Environment=` 形式注入。
5. **前端需自行携带密钥。** `app/` 前端**不发送** `Authorization` 头
   （Vite 只透出 `VITE_*`，见 `app/src/services/apiService.ts`）。
   一旦配置密钥，未改造的前端所有请求都会收到 **401**。见 §7。
6. **修改后重启 API 进程**（`make stop && make serve`）。

---

## 5. 开发模式与严格模式

| `MORE_API_KEY` | `MORE_REQUIRE_API_KEY` | 行为 |
|----------------|------------------------|------|
| 未设置 | 未设置 / `0` | **开发模式**：API 不鉴权，启动时输出 `UNAUTHENTICATED` 告警。 |
| 已设置 | 未设置 / `0` | 正常鉴权；密钥过短时告警。 |
| 未设置 | `1` | **启动失败**，抛 `APIKeyConfigError`。 |
| 格式不合法 | `1` | **启动失败**，抛 `APIKeyConfigError`。 |

默认保持开发模式是既有契约（`tests/test_api.py::TestAuthDependency::test_execute_works_without_key_env`
依赖它）；生产、预发、任何非 localhost 环境**必须**设 `MORE_REQUIRE_API_KEY=1`。

校验入口：`more_core/more_core/api/server.py:validate_api_key()`，在 `create_app()` 中调用。

---

## 6. 轮换

1. 生成新密钥。
2. 更新 `more_core/.env`（或进程管理器中的变量）。
3. 重启 API 进程。
4. 更新所有客户端（脚本的 `Authorization` 头、MCP 客户端的 `MORE_MCP_KEY`）。
5. 旧密钥立即失效——无过渡期、无并存。

MCP 服务端可用 `MORE_MCP_KEY` 单独轮换，与 HTTP 密钥解耦。

---

## 7. 已知约束：前端未接入认证

配置 `MORE_API_KEY` 后，`app/`（端口 3003）会**完全不可用**，因为它从不发送
`Authorization` 头。三个可选方向，需人工决策后再实施（涉及浏览器端密钥存储的安全取舍）：

| 方案 | 说明 |
|------|------|
| 同源反向代理 | 由代理在服务端注入 `Authorization` 头，浏览器不接触密钥。推荐。 |
| 短时效令牌 | 引入登录/换取流程，前端持有短期 token。改动最大。 |
| 本地开发不鉴权 | localhost 保持 `MORE_REQUIRE_API_KEY=0`，仅在受控网络暴露时才启用密钥。 |

**在完成其中之一之前，不要在需要前端的环境中启用 `MORE_REQUIRE_API_KEY=1`。**

---

## 8. 验证

```bash
# 1) 确认变量已被读取（应为已 strip 后的值）
curl -s localhost:8011/api/v1/health -H "Authorization: Bearer $MORE_API_KEY"

# 2) 确认无密钥被拒（期望 401）
curl -s -o /dev/null -w '%{http_code}\n' localhost:8011/api/v1/health

# 3) 确认错误密钥被拒（期望 403）
curl -s -o /dev/null -w '%{http_code}\n' localhost:8011/api/v1/health -H "Authorization: Bearer wrong"

# 4) 确认严格模式会在密钥缺失时阻止启动
MORE_REQUIRE_API_KEY=1 .venv/bin/python -c \
  "import sys; sys.path.insert(0,'more_core'); from more_core.api.server import create_app; create_app()"
```

回归测试：`make test`（`tests/test_api.py` 覆盖 401 / 403 / dev-mode / 严格模式）。

---

## 9. 提交前自检

- [ ] 真实密钥只存在于 `more_core/.env`（已被 `.gitignore` 忽略）
- [ ] `more_core/.env.example`、`.env.template`、`.env.development`、`.env.production`
      中只有占位符（`REPLACE_ME` 等）
- [ ] `app/.env*` 前端环境文件同样不含真实/长时效后端密钥
- [ ] `git status` 中无 `.env*` 变更进入暂存区
- [ ] `git grep -n "sk-more-os-" -- ':!*.template' ':!*.example' ':!docs/*' ':!*.md' ':!*.development' ':!*.production'` 无输出

---

## 10. 多环境配置速查表

| 文件 | MORE_REQUIRE_API_KEY | 用途 | 生效方式 |
|------|----------------------|------|----------|
| `more_core/.env` | 0 (默认) | 日常开发，优先级最低（被 shell/进程 env 覆盖） | 自动加载，模块导入时读取一次 |
| `more_core/.env.development` | 0 | 开发标准配置模板（含 LLM 本地 provider、关闭进化） | `cp/ln -s` 为 `.env`，或 shell `set -a && . && set +a` |
| `more_core/.env.production` | 1（强制） | 生产配置模板（开限流/沙箱加固/强制密钥） | 进程管理器 Environment= 注入；不要软链到公网主机 |
| `more_core/.env.example` | 0 | 新人入门示例，仅含注释与 LM Studio 默认 | 模板，不自动加载 |
| `more_core/.env.template` | 0 | 最全配置项（10+ LLM provider + 全部功能闸门） | 模板，不自动加载 |
| `app/.env.development` | N/A | Vite dev server 读 `VITE_*`；默认不发 Authorization 头 | `npm run dev` 自动加载 |
| `app/.env.production` | N/A | `vite build` 读 `VITE_*`；前端不要放后端共享密钥 | `npm run build` 自动加载 |
