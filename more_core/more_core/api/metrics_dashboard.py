"""零依赖实时指标看板（由 API 自身托管，避免 CORS/密钥泄漏）。

设计取舍：

* 页面本身不含任何密钥；API Key 由使用者在页面上输入，存 ``localStorage``。
* 数据来自 :mod:`more_core.governance.observability` 与
  :mod:`more_core.codegen.delivery_ledger`，因此看板与 API 同源、可随时刷新。
* 纯 HTML/CSS/JS 单文件，无构建步骤、无第三方 CDN 依赖（离线可用）。
"""

from __future__ import annotations

DASHBOARD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MoRE OS — 代码产出运行指标</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0b1020; color:#e6ecff;
         font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }
  header { padding:14px 18px; background:#131a30; border-bottom:1px solid #24304f;
           display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  h1 { font-size:15px; margin:0; font-weight:600; letter-spacing:.4px; }
  input { background:#0b1020; color:#e6ecff; border:1px solid #2b3a5e;
          border-radius:6px; padding:6px 8px; width:280px; }
  button { background:#2b6cff; color:#fff; border:0; border-radius:6px;
           padding:6px 12px; cursor:pointer; }
  .wrap { padding:18px; display:grid; gap:16px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; }
  .card { background:#131a30; border:1px solid #24304f; border-radius:10px; padding:12px 14px; }
  .k { color:#8fa0c8; font-size:11px; text-transform:uppercase; letter-spacing:.6px; }
  .v { font-size:22px; font-weight:700; margin-top:6px; }
  .sub { color:#8fa0c8; font-size:11px; margin-top:4px; }
  table { width:100%; border-collapse:collapse; background:#131a30;
          border:1px solid #24304f; border-radius:10px; overflow:hidden; }
  th,td { padding:7px 10px; text-align:left; border-bottom:1px solid #1d2742; font-size:12px; }
  th { color:#8fa0c8; font-weight:600; }
  .ok { color:#4ade80; } .bad { color:#f87171; } .warn { color:#fbbf24; }
  .bar { height:8px; background:#1d2742; border-radius:4px; overflow:hidden; }
  .bar > i { display:block; height:100%; background:#2b6cff; }
  #err { color:#f87171; }
  .alert { padding:10px 14px; border-radius:8px; border:1px solid; margin:0; }
  .alert.warning  { background:#2a230f; border-color:#7a5b13; color:#fbbf24; }
  .alert.critical { background:#2a1313; border-color:#7a1f1f; color:#f87171; }
  .alert.info { background:#0f1a2a; border-color:#2b3a5e; color:#8fa0c8; }
  .overview { padding:10px 14px; border-radius:8px; border:1px solid #24304f;
              background:#131a30; font-size:13px; }
  .overview.ok   { border-color:#1f5f3a; color:#4ade80; }
  .overview.warn { border-color:#7a5b13; color:#fbbf24; }
  .overview.bad  { border-color:#7a1f1f; color:#f87171; }
</style>
</head>
<body>
<header>
  <h1>MoRE OS · 代码产出运行指标</h1>
  <input id="key" type="password" placeholder="MORE_API_KEY（仅存本机 localStorage）" />
  <button onclick="saveKey()">连接</button>
  <span id="status" class="sub">未连接</span>
  <span id="err"></span>
</header>
<div class="wrap">
  <div id="overview" class="overview">正在加载运行健康总览…</div>
  <div class="cards" id="cards"></div>
  <div id="alerts" class="wrap" style="padding:0;gap:8px"></div>
  <div class="cards" id="gcards"></div>
  <div>
    <div class="k">治理命中规则（近 1h）</div>
    <table id="govrules"><thead><tr><th>规则</th><th>命中</th><th>占比</th><th></th></tr></thead><tbody></tbody></table>
  </div>
  <div>
    <div class="k">按 Provider / Model</div>
    <table id="providers"><thead><tr><th>provider:model</th><th>调用</th><th>成功率</th><th>prompt tok</th><th>completion tok</th></tr></thead><tbody></tbody></table>
  </div>
  <div>
    <div class="k">最近 LLM 调用</div>
    <table id="recent"><thead><tr><th>时间</th><th>provider</th><th>model</th><th>prompt</th><th>completion</th><th>延迟(ms)</th><th>结果</th></tr></thead><tbody></tbody></table>
  </div>
</div>
<script>
const BASE = location.origin;
let key = localStorage.getItem('more_api_key') || '';
document.getElementById('key').value = key;

function saveKey() {
  key = document.getElementById('key').value.trim();
  localStorage.setItem('more_api_key', key);
  refresh();
}
function fmt(n) { return (n ?? 0).toLocaleString(); }
function card(k, v, sub, cls) {
  return `<div class="card"><div class="k">${k}</div><div class="v ${cls||''}">${v}</div>` +
         (sub ? `<div class="sub">${sub}</div>` : '') + `</div>`;
}
async function get(path) {
  const r = await fetch(BASE + path, { headers: { Authorization: 'Bearer ' + key } });
  if (!r.ok) throw new Error(path + ' → HTTP ' + r.status);
  return r.json();
}
async function refresh() {
  const err = document.getElementById('err'), st = document.getElementById('status');
  err.textContent = '';
  if (!key) { st.textContent = '请输入 API Key'; return; }
  try {
    const [m, d, rec, g, c, p, o, sk, sn] = await Promise.all([
      get('/api/v1/metrics/llm?window_s=3600'),
      get('/api/v1/delivery/stats?window_s=86400'),
      get('/api/v1/metrics/llm/recent?limit=15'),
      get('/api/v1/metrics/governance?window_s=3600'),
      get('/api/v1/metrics/council?window_s=3600'),
      get('/api/v1/metrics/providers?window_s=3600'),
      get('/api/v1/metrics/overview?window_s=3600'),
      get('/api/v1/metrics/skills?window_s=3600'),
      get('/api/v1/metrics/skill-network?window_s=3600')
    ]);
    const mm = m.metrics || {}, lat = mm.latency_ms || {}, tok = mm.tokens || {}, ds = d.stats || {};
    const rate = Math.round((mm.success_rate || 0) * 100);
    document.getElementById('cards').innerHTML = [
      card('LLM 调用 (1h)', fmt(mm.samples), `cached ${fmt(mm.cached_calls)}`),
      card('Token 消耗 (1h)', fmt(tok.total), `prompt ${fmt(tok.prompt)} / completion ${fmt(tok.completion)}`),
      card('延迟 p50 / p95', `${fmt(lat.p50)} / ${fmt(lat.p95)} ms`, `avg ${fmt(lat.avg)} · max ${fmt(lat.max)}`),
      card('LLM 成功率', rate + '%', '', rate >= 90 ? 'ok' : (rate >= 70 ? 'warn' : 'bad')),
      card('交付总数 (24h)', fmt(ds.total), `已交付 ${fmt(ds.delivered)} · 拦截 ${fmt(ds.blocked)} · 失败 ${fmt(ds.failed)}`),
      card('交付成功率', Math.round((ds.success_rate || 0) * 100) + '%', `闸门通过率 ${Math.round((ds.gate_pass_rate||0)*100)}%`)
    ].join('');

    const ovMap = {healthy: ['健康', 'ok'], degraded: ['降级', 'warn'], critical: ['严重', 'bad']};
    const ovc = o.alert_counts || {};
    const [ovLabel, ovCls] = ovMap[o.overall] || ['未知', 'warn'];
    document.getElementById('overview').className = 'overview ' + ovCls;
    document.getElementById('overview').innerHTML =
      `运行健康总览：<b>${ovLabel}</b> · 告警 ` +
      `${fmt(ovc.critical)} critical / ${fmt(ovc.warning)} warning · ` +
      `更新 ${new Date((o.generated_at || 0) * 1000).toLocaleTimeString()}`;

    const gm = g.metrics || {}, gbyrule = gm.by_rule || {}, pm = p.health || {};
    const grate = Math.round((gm.blocked_rate || 0) * 100);
    document.getElementById('gcards').innerHTML = [
      card('治理请求 (1h)', fmt(gm.requests), `评估 ${fmt(gm.evaluations)} · 通过 ${fmt(gm.passed)}`),
      card('治理拦截率', grate + '%', `拦截 ${fmt(gm.blocked_requests)} / ${fmt(gm.requests)} 请求`, grate >= 60 ? 'bad' : (grate >= 30 ? 'warn' : 'ok')),
      card('破坏性请求拦截', fmt(gm.destructive_blocks), 'destructive_request_detection', (gm.destructive_blocks||0) > 0 ? 'bad' : 'ok'),
      card('Council 复评 (1h)', fmt((c.metrics||{}).reviews), `下修率 ${Math.round(((c.metrics||{}).downgrade_rate||0)*100)}%`),
      card('Council 平均下修', ((c.metrics||{}).avg_adjustment || 0).toFixed(3), `分歧 ${fmt((c.metrics||{}).divided)} · 高风险 ${fmt((c.metrics||{}).high_risk_reviews)}`, ((c.metrics||{}).avg_adjustment||0) < 0 ? 'warn' : 'ok'),
      card('Provider 健康', `${fmt((pm.n_providers||0) - (pm.n_unhealthy||0))}/${fmt(pm.n_providers||0)}`,
           `无效模型 ${fmt(pm.n_invalid_model)} · 兜底链 ${pm.degraded ? '降级' : 'OK'}`,
           ((pm.n_invalid_model||0) > 0 || (pm.n_unhealthy||0) > 0) ? 'bad' : 'ok'),
      card('技能执行 (1h)', fmt((sk.metrics||{}).runs), `注册 ${fmt((sk.registry||{}).total_skills)} · 活跃 ${fmt((sk.registry||{}).active)}`),
      card('技能成功率', Math.round(((sk.metrics||{}).success_rate||0)*100) + '%',
           `平均 ${fmt((sk.metrics||{}).avg_duration_ms)} ms · p95 ${fmt((sk.metrics||{}).p95_duration_ms)} ms`,
           ((sk.metrics||{}).success_rate||0) >= 0.9 ? 'ok' : 'warn'),
      card('技能出网可达', `${fmt((sn.health||{}).n_reachable)}/${fmt((sn.health||{}).n_targets)}`,
           `依赖技能 ${((sn.health||{}).required_egress||[]).length} 个`,
           ((sn.health||{}).n_targets||0) > 0 && (sn.health||{}).n_reachable < (sn.health||{}).n_targets ? 'bad' : 'ok')
    ].join('');

    document.getElementById('alerts').innerHTML =
      [...(g.alerts || []), ...(p.alerts || []), ...(sn.alerts || [])].map(a =>
        `<div class="alert ${['critical','warning','info'].includes(a.level) ? a.level : 'warning'}">` +
        `[${a.level.toUpperCase()}] ${a.message}</div>`).join('');

    const hits = Object.values(gbyrule).reduce((x, y) => x + y, 0) || 1;
    document.querySelector('#govrules tbody').innerHTML =
      Object.entries(gbyrule).map(([k, v]) => {
        const pct = Math.round(v / hits * 100);
        return `<tr><td>${k}</td><td>${fmt(v)}</td><td>${pct}%</td>` +
               `<td><div class="bar"><i style="width:${pct}%"></i></div></td></tr>`;
      }).join('') || '<tr><td colspan="4" class="sub">暂无治理命中</td></tr>';

    const pb = document.querySelector('#providers tbody');
    pb.innerHTML = Object.entries(mm.providers || {}).map(([k, v]) =>
      `<tr><td>${k}</td><td>${fmt(v.calls)}</td><td>${Math.round(v.success_rate*100)}%</td>` +
      `<td>${fmt(v.prompt_tokens)}</td><td>${fmt(v.completion_tokens)}</td></tr>`).join('')
      || '<tr><td colspan="5" class="sub">暂无数据</td></tr>';

    const rb = document.querySelector('#recent tbody');
    rb.innerHTML = (rec.calls || []).map(c =>
      `<tr><td>${new Date((c.ts||0)*1000).toLocaleTimeString()}</td><td>${c.provider}</td>` +
      `<td>${c.model}</td><td>${fmt(c.prompt_tokens)}</td><td>${fmt(c.completion_tokens)}</td>` +
      `<td>${Math.round(c.latency_ms||0)}</td>` +
      `<td class="${c.success ? 'ok' : 'bad'}">${c.success ? 'OK' : 'FAIL'}</td></tr>`).join('')
      || '<tr><td colspan="7" class="sub">暂无数据</td></tr>';

    st.textContent = '已更新 ' + new Date().toLocaleTimeString();
  } catch (e) {
    err.textContent = String(e.message || e);
    st.textContent = '连接失败';
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
