/**
 * 运行时遥测面板（R-15）。
 *
 * 展示后端**真实采集**的核心运行指标（token 消耗 / 请求延迟 / 成功率 / 交付成功率），
 * 数据来自 `/api/v1/metrics/llm` 与 `/api/v1/delivery/stats`。
 * 同时提供 API Key 配置入口 —— 后端启用 MORE_API_KEY 后，未配置会导致全部 401。
 */
import { useCallback, useEffect, useState } from 'react';
import { Activity, KeyRound, RefreshCw, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ApiError, apiGetJson, getApiKey, setApiKey, hasApiKey } from '@/lib/apiClient';

interface LlmMetrics {
  samples: number;
  success_rate: number;
  tokens: { prompt: number; completion: number; total: number };
  latency_ms: { avg: number; p50: number; p95: number; max: number };
  providers?: Record<string, { calls: number; success_rate: number }>;
  error?: string;
}

interface DeliveryStats {
  total: number;
  delivered: number;
  blocked: number;
  failed: number;
  success_rate: number;
  gate_pass_rate: number;
  /** D-1：阻断原因分布（code_error / sandbox_unavailable / …） */
  blocked_by_cause?: Record<string, number>;
  infra_blocked?: number;
  /** D-4：各层耗时 p50（ms），用于延迟归因 */
  stage_ms_p50?: Record<string, number>;
}

type ConnState = 'idle' | 'loading' | 'ok' | 'unauthorized' | 'offline';

const fmt = (n: number | undefined) => (n ?? 0).toLocaleString();
const pct = (n: number | undefined) => `${Math.round((n ?? 0) * 100)}%`;

export function TelemetryPanel() {
  const [keyInput, setKeyInput] = useState(getApiKey());
  const [metrics, setMetrics] = useState<LlmMetrics | null>(null);
  const [delivery, setDelivery] = useState<DeliveryStats | null>(null);
  const [state, setState] = useState<ConnState>('idle');
  const [error, setError] = useState('');
  // 窗口可选：本地开发经常一两小时内没有新调用，固定 1h 会看不到任何数据
  const [windowS, setWindowS] = useState(3600);

  const refresh = useCallback(async () => {
    setState((s) => (s === 'ok' ? s : 'loading'));
    try {
      const [m, d] = await Promise.all([
        apiGetJson<{ metrics: LlmMetrics }>(`/api/v1/metrics/llm?window_s=${windowS}`),
        apiGetJson<{ stats: DeliveryStats }>('/api/v1/delivery/stats?window_s=86400'),
      ]);
      setMetrics(m.metrics);
      setDelivery(d.stats);
      setState('ok');
      setError('');
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setState('unauthorized');
        setError(e.status === 401 ? '未配置 API Key（后端已启用鉴权）' : 'API Key 无效或无权限');
      } else {
        setState('offline');
        setError(e instanceof Error ? e.message : '服务不可达');
      }
    }
  }, [windowS]);

  useEffect(() => {
    // 首次加载放到下一个 tick：避免在 effect 主体里同步 setState
    // （react-hooks/set-state-in-effect）
    let cancelled = false;
    const tick = () => {
      if (!cancelled) void refresh();
    };
    const initial = setTimeout(tick, 0);
    const id = setInterval(tick, 5000);
    return () => {
      cancelled = true;
      clearTimeout(initial);
      clearInterval(id);
    };
  }, [refresh]);

  const save = () => {
    setApiKey(keyInput);
    void refresh();
  };

  const badge = () => {
    if (state === 'ok') return <span className="flex items-center gap-1 text-green-600"><CheckCircle2 className="w-3.5 h-3.5" />已连接</span>;
    if (state === 'unauthorized') return <span className="flex items-center gap-1 text-amber-600"><AlertTriangle className="w-3.5 h-3.5" />需鉴权</span>;
    if (state === 'offline') return <span className="flex items-center gap-1 text-red-600"><AlertTriangle className="w-3.5 h-3.5" />不可达</span>;
    return <span className="text-gray-500">检测中…</span>;
  };

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-600" />
          <span className="font-semibold text-sm">运行时指标</span>
          <span className="text-xs text-gray-500">{badge()}</span>
        </div>
        <div className="flex items-center gap-1">
          {[
            { label: '1h', value: 3600 },
            { label: '6h', value: 21600 },
            { label: '24h', value: 86400 },
          ].map((w) => (
            <Button
              key={w.value}
              variant={windowS === w.value ? 'secondary' : 'ghost'}
              size="sm"
              className="text-xs px-2"
              aria-pressed={windowS === w.value}
              onClick={() => setWindowS(w.value)}
            >
              {w.label}
            </Button>
          ))}
          <Button variant="ghost" size="sm" className="text-xs" onClick={() => void refresh()}>
            <RefreshCw className="w-3.5 h-3.5 mr-1" />刷新
          </Button>
        </div>
      </div>

      {(state === 'unauthorized' || state === 'offline') && (
        <div className="mb-3 flex items-center gap-2">
          <KeyRound className="w-3.5 h-3.5 text-gray-500" />
          <input
            type="password"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            placeholder="MORE_API_KEY"
            aria-label="API Key"
            className="flex-1 rounded border px-2 py-1 text-xs font-mono"
          />
          <Button size="sm" className="text-xs" onClick={save}>保存并连接</Button>
        </div>
      )}

      {error && <div className="mb-3 text-xs text-amber-700">{error}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-gray-500">LLM 调用</div>
          <div className="font-mono text-lg font-bold">{fmt(metrics?.samples)}</div>
        </div>
        <div>
          <div className="text-gray-500">Token 消耗</div>
          <div className="font-mono text-lg font-bold">{fmt(metrics?.tokens?.total)}</div>
          <div className="text-gray-400">
            prompt {fmt(metrics?.tokens?.prompt)} / completion {fmt(metrics?.tokens?.completion)}
          </div>
        </div>
        <div>
          <div className="text-gray-500">延迟 p50 / p95</div>
          <div className="font-mono text-lg font-bold">
            {fmt(metrics?.latency_ms?.p50)} / {fmt(metrics?.latency_ms?.p95)} ms
          </div>
          <div className="text-gray-400">avg {fmt(metrics?.latency_ms?.avg)} · max {fmt(metrics?.latency_ms?.max)}</div>
        </div>
        <div>
          <div className="text-gray-500">LLM 成功率</div>
          <div className="font-mono text-lg font-bold">{pct(metrics?.success_rate)}</div>
        </div>
        <div>
          <div className="text-gray-500">交付总数（24h）</div>
          <div className="font-mono text-lg font-bold">{fmt(delivery?.total)}</div>
          <div className="text-gray-400">
            已交付 {fmt(delivery?.delivered)} · 拦截 {fmt(delivery?.blocked)} · 失败 {fmt(delivery?.failed)}
          </div>
        </div>
        <div>
          <div className="text-gray-500">交付成功率</div>
          <div className="font-mono text-lg font-bold">{pct(delivery?.success_rate)}</div>
        </div>
        <div>
          <div className="text-gray-500">闸门通过率</div>
          <div className="font-mono text-lg font-bold">{pct(delivery?.gate_pass_rate)}</div>
        </div>
        <div>
          <div className="text-gray-500">凭证状态</div>
          <div className="font-mono text-lg font-bold">{hasApiKey() ? '已配置' : '未配置'}</div>
        </div>
      </div>

      {/* D-1：阻断原因分布（区分"代码真错"与"基础设施问题"） */}
      {delivery?.blocked_by_cause && Object.keys(delivery.blocked_by_cause).length > 0 && (
        <div className="mt-3 text-xs">
          <div className="text-gray-500 mb-1">
            阻断原因分布
            {delivery.infra_blocked ? (
              <span className="ml-2 text-amber-600">
                （其中基础设施类 {delivery.infra_blocked} 条，请先排查沙箱/环境）
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(delivery.blocked_by_cause).map(([cause, count]) => (
              <span
                key={cause}
                className={
                  'rounded px-2 py-0.5 font-mono ' +
                  (cause.startsWith('sandbox_') ? 'bg-amber-100 text-amber-800' : 'bg-gray-100 text-gray-700')
                }
              >
                {cause}: {count}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* D-4：阶段耗时归因 */}
      {delivery?.stage_ms_p50 && Object.keys(delivery.stage_ms_p50).length > 0 && (
        <div className="mt-3 text-xs">
          <div className="text-gray-500 mb-1">阶段耗时 p50（ms）</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(delivery.stage_ms_p50).map(([layer, ms]) => (
              <span key={layer} className="rounded bg-blue-50 px-2 py-0.5 font-mono text-blue-800">
                {layer}: {ms}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default TelemetryPanel;
