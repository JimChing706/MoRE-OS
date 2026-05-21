import type { TaskRequest, TaskResult, SystemState, DashboardData, LayerMetrics } from '@/types/morev3';

const API_BASE_URL = import.meta.env.VITE_API_BASE || 'http://localhost:8001';

class APIService {
  private baseUrl: string;
  private apiKey: string | undefined;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
    this.apiKey = import.meta.env.VITE_BFF_API_KEY;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`;
    }
    if (options.headers) {
      Object.assign(headers, options.headers);
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }

    return response.json();
  }

  async executeTask(request: TaskRequest): Promise<TaskResult> {
    return this.request<TaskResult>('/api/tasks/execute', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async executeTaskStream(
    request: TaskRequest,
    onChunk: (data: any) => void
  ): Promise<void> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`;
    }

    const response = await fetch(`${this.baseUrl}/api/tasks/execute/stream`, {
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
    return this.request<SystemState>('/api/system/state');
  }

  async getTaskHistory(limit: number = 20): Promise<{ tasks: TaskResult[]; total: number }> {
    return this.request<{ tasks: TaskResult[]; total: number }>(`/api/tasks/history?limit=${limit}`);
  }

  async getConfiguredProviders(): Promise<Record<string, { provider: string; model: string; configured: boolean }>> {
    const response = await this.request<{ providers: Record<string, { provider: string; model: string; configured: boolean }> }>('/api/config/providers');
    return response.providers;
  }

  async healthCheck(): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>('/api/health');
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
