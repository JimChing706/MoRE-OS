# MoRE API Key 全流程（生成 → 存储 → 分发 → 生效 → 过期 → 轮换）

**状态**: 已实现并端到端验证（2026-09-29）
**适用版本**: v0.9.9

---

## 1. 设计总览

```
        生成                   存储                     校验 / 生效
┌──────────────────┐   ┌──────────────────────┐   ┌────────────────────────┐
│ generate_api_key │──▶│  APIKeyStore (SQLite)│──▶│ _require_api_key (401) │
│ modern/compat/hex│   │  HMAC-SHA256(pepper) │   │ require_scope (403)    │
└──────────────────┘   └──────────────────────┘   └────────────────────────┘
        │                        │                          │
        │                        ├─ key_id / label / scopes │
        │                        ├─ created_at / expires_at  │
        │                        └─ revoked_at / last_used_at│
        ▼                                                   ▼
   一次性明文返回                                      RBAC + 审计
```

| 能力 | 实现位置 |
|------|----------|
| 生成算法 | `more_core/security/api_key_ops.py::generate_api_key`（compat / modern / hex）+ `validate_api_key_report`（长度/字符集/熵/前缀 7 项报告） |
| 存储 | `more_core/security/api_key_store.py::APIKeyStore`（SQLite，默认 `data/api_keys.db`） |
| 权限校验 | `more_core/api/server.py::_require_api_key` + `more_core/api/auth.py::require_scope` |
| 分发 / 配置 | CLI `more-os api-key issue/inject`、HTTP `POST /api/v1/admin/api-key` |
| 生效 | 每次请求实时校验（无需重启）；env 主密钥热替换需重启 |
| 过期管理 | `expires_at` + `POST /api/v1/admin/api-key/purge` |
| 轮换 | `POST /api/v1/admin/api-key/{key_id}/rotate`（支持宽限期） |
| **分派** | `POST /api/v1/admin/api-key/dispatch`（批量按消费方签发，绑定归属/渠道/配额） |
| **使用管理** | `GET .../api-key/{key_id}/usage`、`.../usage/overview`、`.../attention`；每分钟配额 429 |
| 安全防护 | 只存哈希、pеpper 0600、一次性明文、作用域最小化、吊销即时生效、常量时间比较 |

---

## 2. 密钥格式与生成

| 强度 | 形态 | 用途 |
|------|------|------|
| `modern` | `sk-more-os-` + 48 字符 urlsafe（≈288 bit） | **受管密钥默认**，严格模式要求此前缀 |
| `compat` | 46 字符 urlsafe（≈258 bit） | 兼容 v0.9.9 既有基线 |
| `hex` | 64 位十六进制 | 需要正则安全字符集的工具链 |

```bash
# 仅生成（不落库）
.venv/bin/python -m more_core.cli api-key generate --modern --verbose

# 生成 + 立即注入 .env（带 .bak 备份）
.venv/bin/python -m more_core.cli api-key generate --modern --output-env more_core/.env

# 合规校验（长度 / 字符集 / 熵 / 前缀）
.venv/bin/python -m more_core.cli api-key validate --from-env --strict
```

## 3. 存储与权限模型

* 只持久化 `HMAC-SHA256(pepper, key)`；pepper 来自 `MORE_API_KEY_PEPPER`，
  否则落盘为 `data/.api_key_pepper`（0600，进程外不可读）。
* 每条记录携带 `scopes`。`*` 为通配（env 主密钥与管理员密钥使用）。
* 已实现作用域：

| 作用域 | 覆盖端点 |
|--------|----------|
| `tasks:execute` | `POST /api/v1/tasks/execute`、`POST /api/v1/tasks/{id}/execute`、`POST /api/v1/tasks/stream`、`POST /api/v1/a2a` |
| `admin:apikeys` | `/api/v1/admin/api-key*` 全部管理端点 |
| `*` | 全通配（`MORE_API_KEY` 主密钥） |

## 4. 完整业务链路

```bash
# ① 签发（明文只出现这一次）
curl -s -X POST localhost:8011/api/v1/admin/api-key \
  -H "Authorization: Bearer $MORE_API_KEY" -H 'Content-Type: application/json' \
  -d '{"label":"ci","scopes":["tasks:execute"],"ttl_days":30}'

# ② 分发（示例：写入调用方的 secret store）
export CI_KEY='sk-more-os-...'

# ③ 调用（作用域允许）
curl -s localhost:8011/api/v1/tasks/execute \
  -H "Authorization: Bearer $CI_KEY" -H 'Content-Type: application/json' \
  -d '{"type":"nlp_task","query":"hello"}'

# ④ 越权（作用域拒绝 → 403）
curl -s -X POST localhost:8011/api/v1/admin/api-key \
  -H "Authorization: Bearer $CI_KEY" -d '{"label":"x"}'      # {"detail":"API key lacks required scope 'admin:apikeys'"}

# ⑤ 轮换（旧密钥保留 1 小时宽限）
curl -s -X POST localhost:8011/api/v1/admin/api-key/$KEY_ID/rotate \
  -H "Authorization: Bearer $MORE_API_KEY" -d '{"grace_seconds":3600}'

# ⑥ 吊销（下一请求立即失效）
curl -s -X POST localhost:8011/api/v1/admin/api-key/$KEY_ID/revoke \
  -H "Authorization: Bearer $MORE_API_KEY"

# ⑦ 过期清理
curl -s -X POST "localhost:8011/api/v1/admin/api-key/purge?older_than_seconds=0" \
  -H "Authorization: Bearer $MORE_API_KEY"
```

CLI 等价命令：`api-key issue / list / rotate / revoke`。

## 5. 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `MORE_API_KEY` | 空 | 遗留主密钥（通配作用域）；未设置且注册表为空时 API 处于开发模式（不鉴权） |
| `MORE_API_KEY_DB` | `<repo>/data/api_keys.db` | 受管密钥库路径 |
| `MORE_API_KEY_PEPPER` | 自动生成 | 哈希 pepper；生产建议显式注入并纳入密钥管理 |
| `MORE_REQUIRE_API_KEY` | `0` | `1` = 未配置/格式非法时拒绝启动 |
| `MORE_MASTER_ROTATION_KEY` | 空 | ≥32 字符才启用遗留 env 轮换端点 |
| `MORE_ENV_WRITE_ALLOWLIST` | 空 | 允许 `write_env_file` 写入的额外目录（`os.pathsep` 分隔） |

## 6. 端到端验证证据（2026-09-29）

| 检查项 | 结果 |
|--------|------|
| env 主密钥可访问 | ✅ 200 |
| 无密钥访问 | ✅ 401 |
| 伪造密钥 | ✅ 403 |
| 受管密钥签发 + 一次性明文 | ✅ |
| 作用域允许的调用 | ✅ 200 |
| 作用域越权 | ✅ 403 |
| 明文不落库 | ✅ DB 中检索不到明文 |
| list 不返回明文 | ✅ |
| 轮换（宽限期） | ✅ 旧密钥 200 / 新密钥 200 |
| 轮换（无宽限） | ✅ 旧密钥 403 |
| 吊销后 | ✅ 403 |
| 过期后 | ✅ 403 |
| purge 清理 | ✅ |
| 单元测试 | ✅ `tests/test_api_key_store.py` 16/16 |
| 全量回归 | ✅ 1133 passed / 0 failed |

## 7. 安全加固清单

1. **只存哈希**：明文永不落库，`list` 只返回 `prefix`。
2. **一次性明文**：issue/rotate 响应含明文，此后无法再取回。
3. **pepper 0600**：per-process 隔离；泄漏 DB 不足以致密。
4. **作用域最小化**：签发的调用密钥默认只给 `tasks:execute`。
5. **即时吊销**：`revoked_at` 在下一请求生效，无缓存窗口。
6. **轮换宽限期**：默认 3600s，避免客户端硬切导致中断。
7. **proof 强制**：遗留 env 轮换端点缺少/伪造 HMAC proof 一律 401（不再自签）。
8. **写盘白名单**：`write_env_file` 仅允许仓库 `.env` 或 `MORE_ENV_WRITE_ALLOWLIST` 目录。
9. **常量时间比较**：env 主密钥使用 `hmac.compare_digest`。
10. **测试隔离**：`conftest.py` 强制每用例独立密钥库并清除环境密钥，避免宿主机状态影响结果。

## 8. 已知边界

* 遗留 `MORE_API_KEY` 走进程环境变量，写入 `.env` 后需重启才生效；需要热轮换请使用受管密钥端点。
* 受管密钥的 pepper 若未通过 `MORE_API_KEY_PEPPER` 外部注入，会随 `data/` 一同备份；跨机迁移 DB 必须同时迁移 pepper。
* 当前未实现按 key 的速率限制（复用全局 token bucket）。

---

## 9. 分派（谁在用这把钥匙）

签发只是开始。分派层解决"这把钥匙交给谁、用来做什么、上限多少"。

### 9.1 分派字段

| 字段 | 说明 |
|------|------|
| `owner` | 归属团队 / 租户 |
| `consumer` | 使用方服务名（如 `ci-runner` / `dashboard`） |
| `purpose` | 用途说明 |
| `issued_by` | 签发主体（`admin-api` / `cli` / principal） |
| `channel` | 分发渠道（`api` / `cli` / `secret-manager` …） |
| `quota_per_min` | 每分钟调用上限（留空 = 不限） |

### 9.2 批量分派

```bash
curl -s -X POST localhost:8011/api/v1/admin/api-key/dispatch \
  -H "Authorization: Bearer $MORE_API_KEY" -H 'Content-Type: application/json' \
  -d '{
        "channel": "api",
        "default_scopes": ["tasks:execute"],
        "assignments": [
          {"owner":"team-a","consumer":"ci-runner","purpose":"CI 回归","quota_per_min":3},
          {"owner":"team-b","consumer":"dashboard","purpose":"看板只读","ttl_seconds":86400}
        ]
      }'
```

响应中 `dispatched[].api_key` 是**一次性明文**；随后 `GET /api/v1/admin/api-key`
只返回 `prefix` 与元数据，无法再次取回明文。

CLI 等价：`more-os api-key issue --owner team-a --consumer ci-runner --quota-per-min 3`

---

## 10. 使用管理（配额 · 用量 · 关注清单）

### 10.1 配额执行

`quota_per_min` 采用**滑动窗口**（基于逐次调用明细），超限返回：

```
HTTP 429  {"detail":"API key quota exceeded: 3/3 calls in the last minute (key=key_...)"}
```

设计要点：被拒绝的请求只累加 `denied_count`，**不写入用量明细**，
否则持续重试会不断延长自己的锁定窗口（自锁）。

### 10.2 用量报表

```bash
# 单把密钥
curl -s "localhost:8011/api/v1/admin/api-key/$KEY_ID/usage?window_s=3600" -H "Authorization: Bearer $MORE_API_KEY"
# 或
more-os api-key usage $KEY_ID --window 3600
```

返回：`calls / success / failures / success_rate / tokens /
latency_ms{avg,p50,p95,max} / by_endpoint / by_hour / quota / owner / consumer`。

### 10.3 用量总览与关注清单

```bash
curl -s "localhost:8011/api/v1/admin/api-key/usage/overview?window_s=86400" -H "Authorization: Bearer $MORE_API_KEY"
curl -s "localhost:8011/api/v1/admin/api-key/attention?expiry_days=14&stale_days=30" -H "Authorization: Bearer $MORE_API_KEY"
```

`attention` 分三类：`expiring_soon`（即将过期）、`never_used`（签发后从未使用）、
`expired_pending_purge`（已过期待清理）。

明细清理：`POST /api/v1/admin/api-key/usage/prune?keep_days=7`（保留聚合计数）。

### 10.4 存储结构

* `api_keys`：新增 `owner/consumer/purpose/issued_by/channel/quota_per_min/
  call_count/denied_count/tokens_used/first_used_at/last_used_ip`；
  老库通过 `_migrate()` 幂等补列（已在既有部署上验证）。
* `api_key_usage`：逐次调用明细（`key_id/ts/endpoint/status/latency_ms/tokens/ip`），
  带 `(key_id, ts)` 索引，支撑滑动窗口配额与按小时报表。
* 用量由 **HTTP 中间件** 在响应后统一记录（endpoint + 状态码 + 真实耗时 + 客户端 IP），
  避免每个路由各自埋点。

### 10.5 端到端验证（2026-10-04）

| 检查 | 结果 |
|------|------|
| 批量分派 2 个消费方 | ✅ 归属/渠道/配额正确绑定 |
| 明文只出现一次 | ✅ list 不含明文 |
| 调用被记录 | ✅ calls=3，端点分布/延迟分位齐全 |
| 配额 3/min | ✅ 第 3 次起 429，且不自锁 |
| 单密钥报表 | ✅ owner=team-a |
| 用量总览 | ✅ 含归属与调用量 |
| 关注清单 | ✅ expiring=1 / never_used=3 / expired=1 |
| 老库迁移 | ✅ 3 把历史密钥可读且新字段可用 |
| 全量回归 | ✅ 1206 passed / 0 failed |
