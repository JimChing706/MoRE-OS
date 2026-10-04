import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { TelemetryPanel } from './TelemetryPanel';

const METRICS = {
  samples: 7,
  success_rate: 0.714,
  tokens: { prompt: 16707, completion: 911, total: 17618 },
  latency_ms: { avg: 6419.2, p50: 123.4, p95: 17575.1, max: 17575.1 },
};
const DELIVERY = {
  total: 5, delivered: 4, blocked: 1, failed: 0,
  success_rate: 0.8, gate_pass_rate: 0.8,
  blocked_by_cause: { code_error: 2, sandbox_unavailable: 1 },
  infra_blocked: 1,
  stage_ms_p50: { L0: 812.5, L4: 120.0 },
};

function mockApi(opts: { status?: number } = {}) {
  const status = opts.status ?? 200;
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (status !== 200) {
      return new Response(JSON.stringify({ detail: 'Missing Bearer token' }), { status });
    }
    if (url.includes('/metrics/llm')) {
      return new Response(JSON.stringify({ metrics: METRICS }), { status: 200 });
    }
    return new Response(JSON.stringify({ stats: DELIVERY }), { status: 200 });
  });
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
}

describe('TelemetryPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
      clear: () => undefined,
      key: () => null,
      length: 0,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('渲染真实 token / 延迟 / 成功率指标', async () => {
    mockApi();
    render(<TelemetryPanel />);

    await waitFor(() => expect(screen.getByText('17,618')).toBeInTheDocument());
    expect(screen.getByText('7')).toBeInTheDocument();          // samples
    // 延迟数字被 React 拆成多个文本节点，用正则匹配
    expect(screen.getAllByText(/17,575/).length).toBeGreaterThan(0);
    expect(screen.getAllByText('71%').length).toBeGreaterThan(0);  // LLM 成功率
    expect(screen.getAllByText('80%').length).toBeGreaterThan(0);  // 交付/闸门成功率
    expect(screen.getByText(/prompt 16,707/)).toBeInTheDocument();
  });

  it('后端返回 401 时提示需鉴权并提供 Key 输入', async () => {
    mockApi({ status: 401 });
    render(<TelemetryPanel />);

    await waitFor(() => expect(screen.getByText('需鉴权')).toBeInTheDocument());
    expect(screen.getByLabelText('API Key')).toBeInTheDocument();
    expect(screen.getByText(/未配置 API Key/)).toBeInTheDocument();
  });

  it('保存 Key 后会重新发起请求', async () => {
    const fn = mockApi({ status: 401 });
    render(<TelemetryPanel />);
    await waitFor(() => expect(screen.getByLabelText('API Key')).toBeInTheDocument());

    const before = fn.mock.calls.length;
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'sk-more-os-test' } });
    fireEvent.click(screen.getByText('保存并连接'));

    await waitFor(() => expect(fn.mock.calls.length).toBeGreaterThan(before));
  });

  it('展示阻断原因分布与阶段耗时（D-1 / D-4）', async () => {
    mockApi();
    render(<TelemetryPanel />);

    await waitFor(() => expect(screen.getByText('阻断原因分布')).toBeInTheDocument());
    expect(screen.getByText('code_error: 2')).toBeInTheDocument();
    expect(screen.getByText('sandbox_unavailable: 1')).toBeInTheDocument();
    expect(screen.getByText(/基础设施类 1 条/)).toBeInTheDocument();

    expect(screen.getByText('阶段耗时 p50（ms）')).toBeInTheDocument();
    expect(screen.getByText('L0: 812.5')).toBeInTheDocument();
    expect(screen.getByText('L4: 120')).toBeInTheDocument();
  });
});
