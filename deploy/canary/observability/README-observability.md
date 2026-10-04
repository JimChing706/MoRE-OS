# MoRE OS 运维观测性（Prometheus + Grafana 12 Panel）

**位置**：`deploy/canary/observability/`（本目录）。
**G-2-6 合规**：0 more_core 源码侵入。所有新增文件在 `deploy/canary/` 和 `deploy/canary/scripts/more_prometheus_exporter.py`。

## 组件 3 服务（docker-compose）

| 服务 | 端口（127.0.0.1 绑定）| 默认账号密码 |
|---|---|---|
| Prometheus | http://127.0.0.1:9090 | 无 |
| Grafana | http://127.0.0.1:3000 | **admin / admin** |
| MoRE OS Exporter | http://127.0.0.1:9400/metrics | 无 |

Exporter 指标族 → 见 `deploy/canary/scripts/more_prometheus_exporter.py`。

## 快速开始

```bash
cd deploy/canary/observability

# 1. 语法先校验（强烈推荐）
bash ../../scripts/observability_smoke.sh validate        # 需要 docker compose
# 或手动：
docker compose config >/dev/null  # docker-compose.yml 语法

# 2. 启动（容器后台运行）
docker compose up -d

# 3. 等待 1min，打开 Grafana → Dashboards → MoRE OS → MoRE OS Overview (12 Panel)
open http://127.0.0.1:3000          # 登录 admin/admin

# 4. Prometheus UI：http://127.0.0.1:9090 → Alerts → 6 条告警 rule 全绿
#    Graph：输 more_canary_r2_overall_pass_rate_pct → Execute → 查看 pass_rate 曲线

# 5. 停
docker compose down
# 若连数据一并清空：docker compose down -v
```

### 不使用 Docker / 只在本机裸跑 exporter（推荐 macOS Homebrew 没有 Docker）

```bash
# 仅启动 exporter（Prometheus/Grafana 用户自己另行通过 brew install prometheus/grafana 配）
nohup python3 deploy/canary/scripts/more_prometheus_exporter.py \
  --bind 127.0.0.1 --port 9400 \
  > /tmp/more_exporter.log 2>&1 &

curl -s http://127.0.0.1:9400/metrics   # 验证有 Prometheus text 输出
```

再在 Homebrew Prometheus `prometheus.yml` 里追加：
```yaml
scrape_configs:
  - job_name: more_os_exporter
    static_configs: [{ targets: ["127.0.0.1:9400"] }]
```
然后 `brew services restart prometheus`。

## Dashboard：MoRE OS Overview（`grafana/dashboards/more_os_overview_12panels.json`，uid = `more-os-overview`）

| Panel # | Row | 名称 | 指标（PromQL 片段）| 告警线 |
|---|---|---|---|---|
| 1 | R1 | R1 Echo p95 / p99 ms | `more_canary_r1_echo_p95_ms` + `more_canary_r1_echo_p99_ms` | 红 ≥ 2000ms |
| 2 | R1 | R2 Evolution Pass Rate % | `more_canary_r2_overall_pass_rate_pct` | 红 ≤ 25%；黄 ≤ 35% |
| 3 | R1 | R3 Chassis Delegation Fail % | `more_canary_r3_delegation_fail_rate_pct` | 红 ≥ 5%；黄 ≥ 8% |
| 4 | R1 | R4 Tier Flips / 1h | `more_canary_r4_tier_flips_1h` | 红 ≥ 3；黄 ≥ 5 |
| 5 | R1 | R5 3 Endpoint Healthy 条形 | `more_canary_r5_health` 堆叠 | 死 = RED |
| 6 | R1 | Nginx Weight 饼图 | `more_nginx_weight{target="stable|canary"}` | canary ≥50% + pass<40% = CRITICAL |
| 7 | R2 | 三桶 Pass Rate 对比 多线 | `more_evolution_pass_rate_pct{bucket=~".+"}` | chassis - local ≤ 5pp 告警 |
| 8 | R2 | Bias Applied Count 累计 | `more_evolution_bias_applied_count` | ≥110 OK |
| 9 | R2 | Diff-Uplift Bias 累计 | `more_evolution_diff_uplift_count` | |
| 10 | R2 | Seed-10k / Baseline 占比 | `more_evolution_sample_count` 堆积柱 | |
| 11 | R3 | 4 × Systemd Unit Active 状态卡 | `more_systemd_active{service=~".+"}` → Status 映射 | dead = CRITICAL (2m) |
| 12 | R3 | 告警 Rule 面板（State Timeline）| ALERTS{alertstate!="pending"} | 6 Rule 摘要 |

## 6 条 Alert Rules = `prometheus/alert_rules.yml`（Prometheus → Alertmanager 发送）

1. **CANARY_AUTOROLLBACK_TRIGGERED**（CRITICAL 2m）：`sum(more_canary_light) == 5` → 5 红灯全亮 2 分钟（= canary_monitor 自动回滚条件逼近/已触发）
2. **EVOLUTION_PASS_RATE_LOW**（WARNING 10m）：`more_canary_r2_overall_pass_rate_pct < 35`
3. **CHASSIS_DELEGATION_FAIL_HIGH**（WARNING 5m）：`more_canary_r3_delegation_fail_rate_pct > 8`
4. **TIER_FLIP_EXCESSIVE**（WARNING 5m）：`more_canary_r4_tier_flips_1h > 5`
5. **CANARY_WEIGHT_DANGER**（CRITICAL 8m）：`canary weight ≥50 AND pass_rate<40%`
6. **SYSTEMD_SERVICE_DEAD**（CRITICAL 2m）：`more_systemd_active == 0`

Prometheus → Alertmanager 输出需要另配（默认空 targets），如需 Webhook/钉钉/企业微信：
```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

## 回滚（0 more_core 删除 → 立即回到 Step 6 #2 baseline）

```bash
# A) 仅删除 observability 交付（推荐，保留 Step 6 #2 closed 的其他交付）
rm -rf deploy/canary/observability/
rm deploy/canary/scripts/more_prometheus_exporter.py

# B) 连 Grafana/Prometheus/Exporter 数据/容器一起清（如果 docker compose up -d 过）
cd deploy/canary/observability && docker compose down -v
rm -rf deploy/canary/observability/
rm deploy/canary/scripts/more_prometheus_exporter.py
```

回滚后 **Step 6 #2 的 10,494 total runs 仍然保留（evolution DB 没被观测模块 touched）**。
