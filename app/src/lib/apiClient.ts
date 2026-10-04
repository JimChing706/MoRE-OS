/**
 * 统一 API 客户端（R-15）。
 *
 * 背景：此前 8 个文件、16 处 `fetch` 各自拼接 URL，**都不发送 Authorization 头** ——
 * 后端一旦启用 MORE_API_KEY（本项目已开启严格模式），前端所有请求都会 401。
 *
 * 本模块收口三件事：
 *   1. base URL（`VITE_API_BASE`，默认 http://localhost:8011）
 *   2. API Key 注入（`localStorage` 优先，回退 `VITE_API_KEY`）
 *   3. 统一错误对象 `ApiError`（带 status / detail），便于界面区分 401/403/429
 */

export const API_KEY_STORAGE_KEY = 'more_api_key';
export const API_BASE_STORAGE_KEY = 'more_api_base';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

type EnvLike = { VITE_API_BASE?: string; VITE_API_KEY?: string };

function env(): EnvLike {
  // 兼容 vitest（没有 import.meta.env）与浏览器
  try {
    return (import.meta as unknown as { env?: EnvLike }).env ?? {};
  } catch {
    return {};
  }
}

export function getApiBase(): string {
  const override = storage()?.getItem(API_BASE_STORAGE_KEY) ?? '';
  const base = override || env().VITE_API_BASE || 'http://localhost:8011';
  return base.replace(/\/+$/, '');
}

/** 运行时覆盖 base URL（设置页 / 多环境切换）；传空串恢复默认。 */
export function setApiBase(url: string): void {
  const s = storage();
  if (!s) return;
  const value = (url || '').trim().replace(/\/+$/, '');
  if (value) s.setItem(API_BASE_STORAGE_KEY, value);
  else s.removeItem(API_BASE_STORAGE_KEY);
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

/** 当前生效的 API Key（localStorage 优先，其次构建期注入）。 */
export function getApiKey(): string {
  const stored = storage()?.getItem(API_KEY_STORAGE_KEY) ?? '';
  return (stored || env().VITE_API_KEY || '').trim();
}

export function setApiKey(key: string): void {
  const value = (key || '').trim();
  const s = storage();
  if (!s) return;
  if (value) s.setItem(API_KEY_STORAGE_KEY, value);
  else s.removeItem(API_KEY_STORAGE_KEY);
}

export function clearApiKey(): void {
  setApiKey('');
}

export function hasApiKey(): boolean {
  return getApiKey().length > 0;
}

/** 解析后端错误体（FastAPI 的 detail 可能是字符串或对象）。 */
async function parseError(response: Response): Promise<never> {
  let detail: unknown = undefined;
  try {
    detail = await response.json();
  } catch {
    try {
      detail = await response.text();
    } catch {
      detail = undefined;
    }
  }
  const d = detail as { detail?: unknown } | undefined;
  const raw = d?.detail ?? detail;
  const message =
    typeof raw === 'string'
      ? raw
      : raw
        ? JSON.stringify(raw)
        : `HTTP ${response.status} ${response.statusText}`;
  throw new ApiError(response.status, message, detail);
}

export interface ApiFetchOptions extends RequestInit {
  /** 设为 true 时返回原始 Response（流式 / 非 JSON 场景）。 */
  raw?: boolean;
}

/**
 * 带鉴权的 fetch。
 *
 * - `path` 可以是 `/api/v1/...` 或完整 URL
 * - 自动注入 `Authorization: Bearer <key>`（有 key 时）
 * - 非 2xx 抛出 `ApiError`
 */
export async function apiFetch(path: string, options: ApiFetchOptions = {}): Promise<Response> {
  const { raw, headers, ...rest } = options;
  const url = /^https?:\/\//i.test(path) ? path : `${getApiBase()}${path.startsWith('/') ? '' : '/'}${path}`;

  const merged = new Headers(headers);
  const key = getApiKey();
  if (key && !merged.has('Authorization')) merged.set('Authorization', `Bearer ${key}`);

  const response = await fetch(url, { ...rest, headers: merged });
  if (!response.ok && !raw) await parseError(response);
  return response;
}

/** GET 并解析 JSON。 */
export async function apiGetJson<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const response = await apiFetch(path, options);
  return (await response.json()) as T;
}

/** POST JSON 并解析 JSON。 */
export async function apiPostJson<T>(
  path: string,
  body: unknown,
  options: ApiFetchOptions = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, { ...options, method: options.method ?? 'POST', headers, body: JSON.stringify(body) });
  return (await response.json()) as T;
}

/** 连通性探测：区分"服务不可达"与"鉴权失败"。 */
export async function probeApi(): Promise<{ online: boolean; authorized: boolean; status?: number }> {
  try {
    await apiFetch('/api/v1/health');
    return { online: true, authorized: true, status: 200 };
  } catch (err) {
    if (err instanceof ApiError) {
      return { online: true, authorized: err.status !== 401 && err.status !== 403, status: err.status };
    }
    return { online: false, authorized: false };
  }
}
