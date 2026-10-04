# MoRE OS Canary Rollout Runbook — 单机裸机 nginx 权重金丝雀 + 5 红灯自动回滚

> 生产灰度方案 Step 6 #1 — 批准编号 G-2-1 ~ G-2-7（7/7）+ 4 专家会签门槛通过  
> 架构：3 systemd 服务（stable:8765 / canary:8766 / chassis:9988）+ nginx upstream 权重  
> 节奏：1% → 5% → 50% → 100%（1h / 4h / 24h）

---

## 1. 交付物清单（8 文件）

```
deploy/canary/
├── systemd/
│   ├── more-core-stable.service   # :8765 stable   (MORE_EVOLUTION_READONLY=1)
│   ├── more-core-canary.service   # :8766 canary   (MORE_EVOLUTION_SCHEMA_CEILING=12)
│   ├── blm-chassis.service        # :9988 Rust A2A
│   └── canary-monitor.service     # 5 红灯监控守护（10s 采样 / 3min 滑窗）
├── nginx/
│   └── more_os_canary.conf        # upstream weight 配置（include 进全局 nginx.conf）
├── scripts/
│   ├── canary_monitor.py          # 5 红灯自动回滚（5 条规则见 §5）
│   ├── more-rollout.sh            # CLI: status / start / promote / rollback / finalize
│   └── install_canary.sh          # 一键安装：systemd enable + nginx conf.d 软链
└── README-canary.md               # 本文件
```

## 2. 安装前置条件

| 条件 | 要求 |
|------|------|
| 操作系统 | Linux systemd 发行版（Ubuntu 22.04 / Debian 12 / RHEL 9+）或 macOS launchd（脚本适配中）|
| Python | ≥ 3.11，`more_core` 包已在虚拟环境安装，`python -m more_core serve --help` 可用 |
| Rust | Bailongma chassis release 编译：`cargo build --release`，产出 `bailongma_chassis/target/release/bailongma_chassis` |
| Nginx | ≥ 1.25，`nginx -t` 0 错误，`/etc/nginx/conf.d/` 或 `/usr/local/etc/nginx/conf.d/` 可写 |
| 权限 | 安装需 `sudo`；服务运行账户（`SERVICE_USER=more`）需：`deploy/` 写、`more_core/more_core/data` 写（SQLite WAL 读写）、nginx reload passwordless sudo |

## 3. 一键安装（sudo）

```bash
cd deploy/canary/scripts
# 交互提示设置：MORE_CORE_ROOT / PYTHON_BIN / SERVICE_USER / SERVER_NAME
sudo ./install_canary.sh
```

安装后 `systemctl list-unit-files | grep more-core` 应能看到 4 个 enabled：

```
more-core-stable.service    enabled
more-core-canary.service    enabled
blm-chassis.service         enabled
canary-monitor.service      enabled
```

## 4. Day-1 标准操作流程（从 T0 基线 → T4 全量）

```bash
cd deploy/canary/scripts

# ── Step 1: T0 基线启动（稳定版本 100%，canary 不接流量）───────────────────────
sudo systemctl start more-core-stable blm-chassis
./more-rollout.sh status
# → STAGE: t0 (stable=100% / canary=0%)
# → 观察 30 分钟 baseline p50/p95/pass_rate/Δ 三桶稳定，无异常

# ── Step 2: T1 1% canary（停留 ≥ 1h）──────────────────────────────────────────
sudo systemctl start more-core-canary canary-monitor
./more-rollout.sh start --stage t1
# → nginx reload ≤ 3s；stable=99% canary=1%
watch -n 10 ./more-rollout.sh status
# → 1h 内：echo_ms 正常；pass_rate 无跳崖；tier_flip_1h < 3；全部 OK → 自动提示 promote

# ── Step 3: T2 5% canary（≥ 4h，跨午休/低峰）─────────────────────────────────
./more-rollout.sh promote --to t2
# → 权重 95/5；4h min dwell；继续 watch status

# ── Step 4: T3 50% 半放量（≥ 24h，跨整夜低峰流量）─────────────────────────────
./more-rollout.sh promote --to t3
# → 50/50；24h 期间 p95 / delegation_fail / tier_flip 任一红灯连续 3min → 自动回 T0

# ── Step 5: T4 100% canary（永久）─────────────────────────────────────────────
./more-rollout.sh promote --to t4
# → stable=0 canary=100；继续观察 72h；若全 OK → finalize

# ── Step 6: finalize（canary → 新 stable 长期角色）───────────────────────────
./more-rollout.sh finalize
# → disable more-core-stable.service；保留 canary-monitor（监控 100% canary）
```

## 5. 5 红灯自动回滚规则（`canary_monitor.py`）

**任一红灯 × 连续 3 分钟（10s 采样 = 18+ 样本）命中 → 自动 T0 回滚 ≤ 3s：**

| # | 红灯规则 | 阈值 | 数据来源（已存在端点）| 回滚动作 |
|---|---------|------|-------------------|---------|
| R1 | p95 延迟 | ≥ 2000 ms | canary `/api/v1/a2a` tasks/send echo 实测 | nginx weight 100/0 + reload |
| R2 | overall_pass_rate | ≤ 25% | canary `/api/v1/evolution/summary` overall_pass_rate | 同上 |
| R3 | chassis delegation 失败率 | ≥ 5% | canary `/api/v1/evolution/summary` chassis_* bucket 统计 | 同上 |
| R4 | 1h Tier 翻转次数 | ≥ 3 | canary `/api/v1/llm/routing?tier_transitions_rollup=1h`（P1-4 G-3）| 同上 + POST canary `/api/v1/ops/tier_rollback`（P1-4 G-2 RBAC，prev ladder 回滚）|
| R5 | Health 状态 | 非 200 / status≠healthy | canary `/api/v1/health` | 同上 |

手动一键回滚（任何时刻）：
```bash
./more-rollout.sh rollback --reason "手动：观察到 pass_rate 跳崖 / SRE 人工干预"
```

## 6. 进化 SQLite 共享策略（单文件 + DDL fail-safe）

stable/canary **共享单个** `more_core/more_core/data/codegen_evolution.db`（WAL 模式一写多读）：

| 角色 | DB 权限 | DDL 护栏（schema_version fail-safe）| 写入标签 |
|------|---------|----------------------------------|---------|
| stable (:8765) | 只读（`MORE_EVOLUTION_READONLY=1`）| N/A | N/A |
| canary (:8766) | 读写 | 启动前 `PRAGMA schema_version` ≤ `MORE_EVOLUTION_SCHEMA_CEILING=12`，**大于则拒绝启动**（防止 canary 跑未验收 DDL 污染 stable 可启动性）| 所有写入行 `artifacts_json.run_context.version="canary"`（`CodegenRunContext.version` 已自动写入），回滚不删除 → 偏置继续正向累积 |

## 7. 事故响应 Runbook（SRE / On-Call）

### 7.1 金丝雀自动回滚告警
`journalctl -u canary-monitor.service -n 200` 找 `CANARY AUTO-ROLLBACK triggered`：
```
Sep 26 15:32:01 prod-node canary-monitor[1234]: CRITICAL CANARY AUTO-ROLLBACK triggered. Red lights: {'R1': True}
Sep 26 15:32:01 prod-node canary-monitor[1234]: Rollback result: cfg_rewritten=True nginx_reloaded=True
```
- 已自动：nginx 100/0 + POST tier_rollback（若有 API Key）
- SRE 动作：
  1. 确认 stable 端指标恢复（`more-rollout.sh status`）
  2. 诊断 canary 日志 `journalctl -u more-core-canary.service --since "20 min ago"`
  3. 修复 canary → 重启 `more-core-canary` → 从 T1 1% 重新开始

### 7.2 nginx reload 失败（极少见）
`nginx -t` 失败 → 回滚 nginx conf 到 backup：
```bash
cp /etc/nginx/conf.d/more_os_canary.conf /tmp/more_os_canary.conf.bad.$(date +%s)
# 手动写 100/0
python - <<'PY'
import re
p="/etc/nginx/conf.d/more_os_canary.conf"
s=open(p).read()
s=re.sub(r"(server 127\.0\.0\.1:8765\s+weight=)\d+", r"\g<1>100", s)
s=re.sub(r"(server 127\.0\.0\.1:8766\s+weight=)\d+", r"\g<1>0",   s)
open(p,"w").write(s)
PY
nginx -t && sudo -n nginx -s reload
```

### 7.3 canary 服务持续崩（启动循环）
- `systemctl stop more-core-canary; systemctl disable more-core-canary` 强制停
- 诊断：`journalctl -u more-core-canary.service -n 200` → 常见：`MORE_EVOLUTION_SCHEMA_CEILING=12` fail-safe 触发（升级 schema_version 前必须先升级 baseline stable）

## 8. 验收（Step 6 #1 passed = 8/8）

| # | 验收项 | 命令 | 目标 |
|---|-------|------|------|
| 1 | 4 systemd 服务 enabled | `systemctl is-enabled more-core-stable more-core-canary blm-chassis canary-monitor` | 4/4 enabled |
| 2 | nginx 4 阶段 weight 切换 + nginx -t | `more-rollout.sh promote --to t1` 逐阶段 | nginx -t 通过，4 阶段权重正确 |
| 3 | 红灯 R1 注入 → 自动回滚 | 注入 p95=3000ms × 4min → 查 status T0 | ≤ 3s 回 100:0 ✅ |
| 4 | promote CLI t1→t2→t3→t4 + status 输出 | 逐阶段 promote | status 阶段名、dwell、monitor 窗口正确 |
| 5 | canary schema_version fail-safe | 写 MORE_EVOLUTION_SCHEMA_CEILING=0 → start canary | canary 启动拒绝（fail-safe）|
| 6 | canary codegen 100 次后 DB version 标签 | 100 codegen → SQL `WHERE artifacts_json LIKE '%"version":"canary"%'` | 100/100 带标签 |
| 7 | 回滚 10 min 后 stable pass_rate ±1pp | 比较回滚前后 summary.overall_pass_rate | |Δ| ≤ 1pp |
| 8 | 最终闸 `pytest more_core/tests/` + diagnostics 0 | `cd more_core && pytest tests/` + GetDiagnostics | 1025 passed 1 warning / 0 diagnostics |

## 9. 合规约束（永久生效）

- ✅ G-2-6：**不侵入 `more_core/` 源码**，本次交付所有新文件均在 `deploy/canary/` 下，回滚即 `rm -rf deploy/canary/` + 删 systemd + nginx 软链 → 恢复 Step 5 基线（1025 passed）
- ✅ G-2-5：DB 共享策略严格写标签 + schema ceiling fail-safe，未验收 canary 绝不允许 schema DDL
- ✅ G-2-4：5 红灯 100% 复用 P0/P1/P1-4 G-3 已有端点，**不新造指标 / 不新造私有协议**
- ✅ 5 红灯全验证：自动回滚 = `nginx -t && nginx -s reload` 原子两步，绝不跳过 `nginx -t`

---

*Runbook 版本：v1.0（批准编号 G-2-1…G-2-7 全通过）| 责任人：Step 6 #1 灰度 Rollout Lead*
