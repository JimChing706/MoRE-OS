import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  API_BASE_STORAGE_KEY,
  API_KEY_STORAGE_KEY,
  ApiError,
  apiFetch,
  apiGetJson,
  apiPostJson,
  clearApiKey,
  getApiBase,
  getApiKey,
  hasApiKey,
  probeApi,
  setApiBase,
  setApiKey,
} from './apiClient';

const ORIGINAL_FETCH = globalThis.fetch;

function mockFetch(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    impl(String(input), init),
  );
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
}

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('apiClient', () => {
  // 显式 stub：不依赖 jsdom 是否把 localStorage 暴露到全局
  let store: Map<string, string>;

  beforeEach(() => {
    store = new Map();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, String(v)),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      get length() {
        return store.size;
      },
    });
    setApiBase('http://test.local:9999');
    clearApiKey();
  });

  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
    vi.unstubAllGlobals();
  });

  describe('API Key 管理', () => {
    it('未配置时为空且 hasApiKey=false', () => {
      expect(getApiKey()).toBe('');
      expect(hasApiKey()).toBe(false);
    });

    it('setApiKey 会持久化到 localStorage', () => {
      setApiKey('  sk-more-os-abc  ');
      expect(getApiKey()).toBe('sk-more-os-abc');
      expect(localStorage.getItem(API_KEY_STORAGE_KEY)).toBe('sk-more-os-abc');
      expect(hasApiKey()).toBe(true);
    });

    it('clearApiKey 清空', () => {
      setApiKey('k');
      clearApiKey();
      expect(getApiKey()).toBe('');
    });
  });

  describe('base URL', () => {
    it('可运行时覆盖', () => {
      setApiBase('http://api.example.com/');
      expect(getApiBase()).toBe('http://api.example.com');
      expect(localStorage.getItem(API_BASE_STORAGE_KEY)).toBe('http://api.example.com');
    });

    it('传空串恢复默认', () => {
      setApiBase('http://x.local');
      setApiBase('');
      expect(getApiBase()).not.toBe('http://x.local');
    });
  });

  describe('apiFetch', () => {
    it('配置了 key 时注入 Authorization', async () => {
      setApiKey('sk-test-123');
      const fn = mockFetch(async () => jsonResponse({ ok: true }));
      await apiFetch('/api/v1/health');
      const [, init] = fn.mock.calls[0];
      const headers = new Headers(init?.headers);
      expect(headers.get('Authorization')).toBe('Bearer sk-test-123');
    });

    it('未配置 key 时不注入 Authorization', async () => {
      const fn = mockFetch(async () => jsonResponse({ ok: true }));
      await apiFetch('/api/v1/health');
      const headers = new Headers(fn.mock.calls[0][1]?.headers);
      expect(headers.get('Authorization')).toBeNull();
    });

    it('拼接 base URL', async () => {
      const fn = mockFetch(async () => jsonResponse({}));
      await apiFetch('/api/v1/metrics/llm');
      expect(fn.mock.calls[0][0]).toBe('http://test.local:9999/api/v1/metrics/llm');
    });

    it('非 2xx 抛 ApiError 并解析 detail', async () => {
      mockFetch(async () => jsonResponse({ detail: 'Missing Bearer token' }, 401));
      await expect(apiFetch('/api/v1/health')).rejects.toBeInstanceOf(ApiError);
      await expect(apiFetch('/api/v1/health')).rejects.toMatchObject({
        status: 401,
        message: 'Missing Bearer token',
      });
    });

    it('raw: true 时不抛错，交由调用方判断', async () => {
      mockFetch(async () => jsonResponse({ detail: 'nope' }, 403));
      const res = await apiFetch('/api/v1/health', { raw: true });
      expect(res.status).toBe(403);
    });
  });

  describe('JSON 便捷方法', () => {
    it('apiGetJson 解析响应体', async () => {
      mockFetch(async () => jsonResponse({ metrics: { samples: 3 } }));
      const data = await apiGetJson<{ metrics: { samples: number } }>('/api/v1/metrics/llm');
      expect(data.metrics.samples).toBe(3);
    });

    it('apiPostJson 发送 JSON 且带 Content-Type', async () => {
      const fn = mockFetch(async () => jsonResponse({ ok: true }));
      await apiPostJson('/api/v1/tasks/execute', { query: 'hi' });
      const [, init] = fn.mock.calls[0];
      expect(init?.method).toBe('POST');
      expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json');
      expect(init?.body).toBe(JSON.stringify({ query: 'hi' }));
    });
  });

  describe('probeApi', () => {
    it('鉴权失败时区分 online/authorized', async () => {
      mockFetch(async () => jsonResponse({ detail: 'Missing' }, 401));
      await expect(probeApi()).resolves.toMatchObject({ online: true, authorized: false, status: 401 });
    });

    it('网络异常时 online=false', async () => {
      mockFetch(async () => {
        throw new TypeError('Failed to fetch');
      });
      await expect(probeApi()).resolves.toMatchObject({ online: false, authorized: false });
    });
  });
});
