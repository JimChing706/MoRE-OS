import type { TaskRequest, TaskResult, SystemState, DashboardData, LayerMetrics } from '@/types/morev3';

const API_BASE_URL = import.meta.env.VITE_API_BASE || 'http://localhost:8011';

// ── 增强配置 ──
const REQUEST_TIMEOUT_MS = 15_000;
const RETRY_MAX = 2;
const RETRY_BASE_DELAY_MS = 500;
const HEALTH_CHECK_INTERVAL_MS = 30_000;
const CIRCUIT_BREAKER_THRESHOLD = 3;
const CIRCUIT_RESET_MS = 60_000;

export class ApiError extends Error {
  readonly status?: number;
  readonly isNetworkError: boolean = false;
  readonly isTimeout: boolean = false;

  constructor(
    message: string,
    status?: number,
    isNetworkError: boolean = false,
    isTimeout: boolean = false
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.isNetworkError = isNetworkError;
    this.isTimeout = isTimeout;
  }
}

class APIService {
  private baseUrl: string;
  private _healthStatus: { online: boolean; lastCheck: number; consecutiveErrors: number; version: string } = {
    online: false, lastCheck: 0, consecutiveErrors: 0, version: 'unknown',
  };
  private _healthListeners = new Set<(online: boolean) => void>();

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  // ── 健康状态订阅 ──
  get healthOnline(): boolean { return this._healthStatus.online; }
  get healthVersion(): string { return this._healthStatus.version; }

  onHealthChange(fn: (online: boolean) => void): () => void {
    this._healthListeners.add(fn);
    return () => this._healthListeners.delete(fn);
  }

  private _notifyHealth(online: boolean) {
    this._healthStatus.online = online;
    this._healthListeners.forEach(fn => fn(online));
  }

  async checkHealth(): Promise<boolean> {
    const now = Date.now();
    // 熔断器：连续失败过多时跳过检查
    if (this._healthStatus.consecutiveErrors >= CIRCUIT_BREAKER_THRESHOLD &&
        now - this._healthStatus.lastCheck < CIRCUIT_RESET_MS) {
      return false;
    }

    try {
      const res = await this._fetchWithTimeout(`${this.baseUrl}/api/v1/health`, {}, 5000);
      const online = res.ok;
      if (online) {
        this._healthStatus.consecutiveErrors = 0;
        try {
          const body = await res.json();
          if (body?.version) this._healthStatus.version = body.version;
        } catch { /* keep old version */ }
      } else {
        this._healthStatus.consecutiveErrors++;
      }
      this._healthStatus.lastCheck = now;
      if (online !== this._healthStatus.online) {
        this._notifyHealth(online);
      }
      return online;
    } catch {
      this._healthStatus.consecutiveErrors++;
      this._healthStatus.lastCheck = now;
      if (this._healthStatus.online) {
        this._notifyHealth(false);
      }
      return false;
    }
  }

  startHealthPolling(intervalMs = HEALTH_CHECK_INTERVAL_MS): () => void {
    this.checkHealth();
    const id = setInterval(() => this.checkHealth(), intervalMs);
    return () => clearInterval(id);
  }

  // ── 核心请求方法（含超时 + 重试） ──
  private async _fetchWithTimeout(
    url: string, options: RequestInit, timeoutMs: number = REQUEST_TIMEOUT_MS
  ): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      return response;
    } finally {
      clearTimeout(timer);
    }
  }

  private async request<T>(
    endpoint: string, options: RequestInit = {}, retries: number = RETRY_MAX
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (options.headers) {
      Object.assign(headers, options.headers);
    }

    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const response = await this._fetchWithTimeout(url, { ...options, headers });

        if (!response.ok) {
          throw new ApiError(
            `服务器错误 ${response.status}: ${response.statusText}`,
            response.status, false, false
          );
        }

        return response.json();
      } catch (err: unknown) {
        const error = err instanceof Error ? err : new Error(String(err));
        lastError = error;

        const isAbort = error.name === 'AbortError';
        const isNetErr = error instanceof TypeError ||
          error.message?.includes('Failed to fetch') ||
          error.message?.includes('NetworkError');

        if (isAbort || isNetErr) {
          if (attempt < retries) {
            const delay = RETRY_BASE_DELAY_MS * Math.pow(2, attempt);
            console.warn(`[API] 请求失败，${delay}ms 后重试 (${attempt + 1}/${retries}): ${endpoint}`);
            await new Promise(r => setTimeout(r, delay));
            continue;
          }
          throw new ApiError(
            isAbort ? '请求超时，无法连接到 API 服务' : '网络连接失败，请检查 API 服务是否运行',
            undefined, true, isAbort
          );
        }

        // 非网络错误不重试（如 4xx/5xx）
        throw err instanceof ApiError ? err : new ApiError(error.message || String(error));
      }
    }

    throw lastError ?? new ApiError('未知请求错误');
  }

  async executeTask(request: TaskRequest): Promise<TaskResult> {
    return this.request<TaskResult>('/api/v1/tasks/execute', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async executeTaskStream(
    request: TaskRequest,
    onChunk: (data: unknown) => void
  ): Promise<void> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    const response = await fetch(`${this.baseUrl}/api/v1/tasks/execute/stream`, {
      method: 'POST',
      body: JSON.stringify(request),
      headers,
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            onChunk(data);
          } catch (e) {
            console.error('Failed to parse SSE data:', e);
          }
        }
      }
    }
  }

  async getSystemState(): Promise<SystemState> {
    return this.request<SystemState>('/api/v1/system/state');
  }

  async getTaskHistory(limit: number = 20): Promise<{ tasks: TaskResult[]; total: number }> {
    return this.request<{ tasks: TaskResult[]; total: number }>(`/api/v1/tasks/history?limit=${limit}`);
  }

  async getConfiguredProviders(): Promise<Record<string, { provider: string; model: string; configured: boolean }>> {
    const response = await this.request<{ providers: Record<string, { provider: string; model: string; configured: boolean }> }>('/api/v1/config/providers');
    return response.providers;
  }

  async healthCheck(): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>('/api/v1/health');
  }

  async getDashboardData(): Promise<DashboardData> {
    const [systemState, taskHistory] = await Promise.all([
      this.getSystemState(),
      this.getTaskHistory(10),
    ]);

    const layerMetrics: LayerMetrics[] = [
      { layerId: 'L0', layerName: '执行层', tasksProcessed: 150, avgLatency: 50, successRate: 0.95, engineUtilization: 0.6, activeEngines: 3 },
      { layerId: 'L1', layerName: '协作编排层', tasksProcessed: 120, avgLatency: 80, successRate: 0.92, engineUtilization: 0.55, activeEngines: 3 },
      { layerId: 'L2', layerName: '神经进化层', tasksProcessed: 90, avgLatency: 120, successRate: 0.88, engineUtilization: 0.65, activeEngines: 3 },
      { layerId: 'L3', layerName: '符号推理层', tasksProcessed: 100, avgLatency: 100, successRate: 0.90, engineUtilization: 0.50, activeEngines: 3 },
      { layerId: 'L4', layerName: '认知层', tasksProcessed: 110, avgLatency: 90, successRate: 0.91, engineUtilization: 0.52, activeEngines: 3 },
      { layerId: 'L5', layerName: '元认知层', tasksProcessed: 80, avgLatency: 110, successRate: 0.89, engineUtilization: 0.45, activeEngines: 3 },
    ];

    return {
      systemState: {
        ...systemState,
        engineStatuses: {
          L0: [{ id: 'tool_executor', name: '工具执行器', description: '执行工具调用', status: 'running', capabilities: ['tool_invocation'], loadFactor: 0.5 }],
          L1: [{ id: 'omac_optimizer', name: 'OMAC优化器', description: '协作优化', status: 'running', capabilities: ['optimization'], loadFactor: 0.45 }],
          L2: [{ id: 'dgm_engine', name: 'DGM引擎', description: '进化机制', status: 'running', capabilities: ['evolution'], loadFactor: 0.55 }],
          L3: [{ id: 'rule_engine', name: '规则引擎', description: '符号推理', status: 'running', capabilities: ['reasoning'], loadFactor: 0.40 }],
          L4: [{ id: 'task_parser', name: '任务解析器', description: '语义理解', status: 'running', capabilities: ['parsing'], loadFactor: 0.48 }],
          L5: [{ id: 'hyperagent', name: 'HyperAgent', description: '元认知', status: 'running', capabilities: ['metacognition'], loadFactor: 0.42 }],
        },
        evolutionArchive: {
          agents: [],
          branches: [],
          currentBest: '',
          archiveSize: 0,
          maxArchiveSize: 500,
        },
        ontologyConstraints: [
          { entity: 'Agent', rule: '所有Agent必须经过沙箱验证', priority: 10, enforced: true },
          { entity: 'Policy', rule: '元认知修改需人类审核', priority: 9, enforced: true },
          { entity: 'Confidence', rule: '置信度<0.6触发重试', priority: 7, enforced: true },
          { entity: 'Outcome', rule: '输出需通过本体验证', priority: 8, enforced: true },
        ],
      },
      recentTasks: taskHistory.tasks,
      memorySystem: {
        episodic: [],
        semantic: [],
        procedural: [],
      },
      safetyEvents: [
        { id: 'sev_001', severity: 'low', type: 'sandbox_breach', description: '沙箱执行超时', layer: 'L0', timestamp: Date.now() - 3600000, resolved: true },
      ],
      layerMetrics,
      evolutionStats: {
        totalAgents: 26,
        totalBranches: 4,
        currentBestScore: 0.63,
        improvementRate: 0.015,
        activeMutations: 5,
        convergenceStatus: 'exploring',
      },
    };
  }
}

export const apiService = new APIService();
export default apiService;
