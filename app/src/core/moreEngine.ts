// ============================================================
// MoRE v3.0 — 核心引擎系统
// ============================================================

import type {
  LayerDefinition, LayerId, TaskRequest, TaskResult, ReasoningStep,
  PerformanceMetrics, RoutingDecision, SystemState, MemorySystem,
  EvolutionArchive, SafetyEvent,
  DashboardData, EvolutionStats,
  MetacognitiveCalibration, EngineDefinition,
  EvolvedAgent, EvolutionBranch, Mutation, TaskType, MemoryEntry,
} from '@/types/morev3';

// --- 六层架构定义 ---

export const LAYER_DEFINITIONS: LayerDefinition[] = [
  {
    id: 'L5',
    name: '元认知层',
    englishName: 'Metacognition',
    description: '自我监控、策略选择、能力评估、校准反馈。集成HyperAgents实现元认知自修改。',
    features: ['自我监控', '策略选择', '能力评估', '校准反馈', '元级迁移'],
    color: '#FF6F00',
    engines: [
      { id: 'hyperagent', name: 'HyperAgent引擎', description: '元认知自修改核心', status: 'running', capabilities: ['self_modification', 'strategy_evolution', 'cross_domain_transfer'], loadFactor: 0.45 },
      { id: 'calibrator', name: '校准器', description: '置信度-准确度对齐', status: 'running', capabilities: ['confidence_calibration', 'error_detection'], loadFactor: 0.32 },
      { id: 'strategy_selector', name: '策略选择器', description: '最优推理策略选择', status: 'idle', capabilities: ['strategy_selection', 'difficulty_assessment'], loadFactor: 0.15 },
    ],
    inputTypes: ['task_request', 'performance_feedback', 'evolution_signal'],
    outputTypes: ['strategy', 'calibration_report', 'meta_report'],
  },
  {
    id: 'L4',
    name: '认知层',
    englishName: 'Cognition',
    description: '任务理解、策略评估、资源分配、难度感知。',
    features: ['任务理解', '策略评估', '资源分配', '难度感知', '长程规划'],
    color: '#FF8F00',
    engines: [
      { id: 'task_parser', name: '任务解析器', description: '深度语义理解', status: 'running', capabilities: ['semantic_parsing', 'intent_recognition'], loadFactor: 0.38 },
      { id: 'resource_allocator', name: '资源分配器', description: '计算资源动态分配', status: 'running', capabilities: ['resource_scheduling', 'load_balancing'], loadFactor: 0.55 },
      { id: 'planner', name: '规划引擎', description: '长程规划与子任务分解', status: 'idle', capabilities: ['task_decomposition', 'plan_generation'], loadFactor: 0.22 },
    ],
    inputTypes: ['parsed_task', 'context'],
    outputTypes: ['plan', 'resource_request', 'difficulty_estimate'],
  },
  {
    id: 'L3',
    name: '符号推理层',
    englishName: 'Symbolic Reasoning',
    description: '本体约束、逻辑验证、规则引擎、形式化证明。集成NSPA-AI神经符号架构。',
    features: ['本体约束', '逻辑验证', '规则引擎', '形式化证明', '神经符号融合'],
    color: '#FFA000',
    engines: [
      { id: 'ontology_engine', name: '本体引擎', description: 'AOW + 领域本体', status: 'running', capabilities: ['ontology_reasoning', 'constraint_checking'], loadFactor: 0.42 },
      { id: 'rule_engine', name: '规则引擎', description: '基于本体的推理', status: 'running', capabilities: ['rule_execution', 'inference'], loadFactor: 0.28 },
      { id: 'nspa_integrator', name: 'NSPA-AI集成器', description: '神经符号融合推理', status: 'running', capabilities: ['neuro_symbolic_fusion', 'prototype_matching'], loadFactor: 0.35 },
    ],
    inputTypes: ['task', 'ontology_query'],
    outputTypes: ['reasoning_result', 'verification_report'],
  },
  {
    id: 'L2',
    name: '神经进化层',
    englishName: 'Neural-Evolution',
    description: 'DGM进化、HyperAgent自我修改、开放探索。',
    features: ['DGM进化', 'HyperAgent自修改', '开放探索', 'Agent归档', '突变生成'],
    color: '#FFB300',
    engines: [
      { id: 'dgm_engine', name: 'DGM引擎', description: '达尔文进化机制', status: 'running', capabilities: ['code_evolution', 'mutation_generation', 'fitness_evaluation'], loadFactor: 0.65 },
      { id: 'archive_manager', name: '归档管理器', description: 'Agent版本树管理', status: 'running', capabilities: ['version_control', 'branching', 'lineage_tracking'], loadFactor: 0.30 },
      { id: 'explorer', name: '探索引擎', description: '开放域探索', status: 'evolving', capabilities: ['open_ended_exploration', 'stepping_stone_discovery'], loadFactor: 0.50 },
    ],
    inputTypes: ['agent_code', 'fitness_signal'],
    outputTypes: ['evolved_agent', 'exploration_result'],
  },
  {
    id: 'L1',
    name: '协作编排层',
    englishName: 'Orchestration',
    description: 'OMAC优化、MARL训练、动态路由、负载均衡。',
    features: ['OMAC优化', 'MARL训练', '动态路由', '负载均衡', '协作结构优化'],
    color: '#FFC107',
    engines: [
      { id: 'omac_optimizer', name: 'OMAC优化器', description: '五维协作优化', status: 'running', capabilities: ['function_optimization', 'structure_optimization', 'joint_optimization'], loadFactor: 0.48 },
      { id: 'marl_trainer', name: 'MARL训练器', description: '多Agent强化学习', status: 'running', capabilities: ['multi_agent_rl', 'emergent_collaboration'], loadFactor: 0.60 },
      { id: 'router', name: '动态路由器', description: '任务特征驱动的引擎选择', status: 'running', capabilities: ['adaptive_routing', 'difficulty_aware_scheduling'], loadFactor: 0.40 },
    ],
    inputTypes: ['task', 'agent_capabilities'],
    outputTypes: ['routing_decision', 'training_result'],
  },
  {
    id: 'L0',
    name: '执行层',
    englishName: 'Execution',
    description: '工具调用、代码执行、API接口、沙箱环境。',
    features: ['工具调用', '代码执行', 'API接口', '沙箱环境', '安全隔离'],
    color: '#FFD54F',
    engines: [
      { id: 'tool_executor', name: '工具执行器', description: '安全沙箱工具调用', status: 'running', capabilities: ['tool_invocation', 'sandbox_execution'], loadFactor: 0.52 },
      { id: 'code_interpreter', name: '代码解释器', description: 'Python/Shell执行', status: 'running', capabilities: ['code_execution', 'result_parsing'], loadFactor: 0.45 },
      { id: 'api_gateway', name: 'API网关', description: '外部服务接口', status: 'running', capabilities: ['api_call', 'service_integration'], loadFactor: 0.35 },
    ],
    inputTypes: ['execution_request'],
    outputTypes: ['execution_result', 'tool_output'],
  },
];

// --- 模拟校准数据生成 ---
function generateCalibration(): MetacognitiveCalibration {
  const history: MetacognitiveCalibration['history'] = [];
  let conf = 0.7 + Math.random() * 0.2;
  let acc = 0.65 + Math.random() * 0.25;
  for (let i = 0; i < 20; i++) {
    conf += (Math.random() - 0.5) * 0.1;
    acc += (Math.random() - 0.5) * 0.08;
    conf = Math.max(0.3, Math.min(0.95, conf));
    acc = Math.max(0.3, Math.min(0.95, acc));
    history.push({
      timestamp: Date.now() - (20 - i) * 60000,
      confidence: conf,
      actualAccuracy: acc,
    });
  }
  const last = history[history.length - 1];
  return {
    confidence: last.confidence,
    accuracy: last.actualAccuracy,
    alignment: 1 - Math.abs(last.confidence - last.actualAccuracy),
    history,
  };
}

// --- 模拟进化归档 ---
function generateEvolutionArchive(): EvolutionArchive {
  const branches: EvolutionBranch[] = [
    { id: 'main', name: '主分支', rootAgentId: 'agent_v0', agentCount: 12, bestPerformance: 0.55, isActive: true },
    { id: 'explore_symbolic', name: '符号推理探索', rootAgentId: 'agent_v3', agentCount: 8, bestPerformance: 0.48, isActive: true },
    { id: 'explore_meta', name: '元认知探索', rootAgentId: 'agent_v5', agentCount: 15, bestPerformance: 0.63, isActive: true },
    { id: 'legacy', name: '遗留分支', rootAgentId: 'agent_v0', agentCount: 5, bestPerformance: 0.35, isActive: false },
  ];

  const agents: EvolvedAgent[] = [];
  for (let g = 0; g <= 25; g++) {
    const branch = branches[Math.floor(Math.random() * 3)];
    const parent = g > 0 ? agents.find(a => a.generation === g - 1 && a.branch === branch.id) : undefined;
    const perf = Math.min(0.75, 0.20 + g * 0.015 + Math.random() * 0.05);
    agents.push({
      id: `agent_v${g}_${Math.random().toString(36).substr(2, 4)}`,
      parentId: parent?.id,
      generation: g,
      code: `// evolved agent generation ${g}\nclass Agent { ... }`,
      performance: perf,
      mutations: [{
        type: ['code_change', 'strategy_change', 'parameter_tune'][Math.floor(Math.random() * 3)] as Mutation['type'],
        description: `Generation ${g} optimization`,
        diff: `+ improved reasoning`,
        verified: perf > 0.4,
      }],
      createdAt: Date.now() - (25 - g) * 3600000,
      branch: branch.id,
    });
  }

  return {
    agents,
    branches,
    currentBest: agents.reduce((a, b) => a.performance > b.performance ? a : b).id,
    archiveSize: agents.length,
    maxArchiveSize: 500,
  };
}

// --- 模拟推理链生成 ---
function generateReasoningChain(_taskId: string, layers: LayerId[]): ReasoningStep[] {
  const steps: ReasoningStep[] = [];
  let time = Date.now() - 3000;
  layers.forEach((layer, i) => {
    const step: ReasoningStep = {
      id: i + 1,
      layer,
      description: getStepDescription(layer, i),
      duration: 50 + Math.random() * 450,
      inputTokens: Math.floor(100 + Math.random() * 900),
      outputTokens: Math.floor(50 + Math.random() * 400),
      confidence: 0.7 + Math.random() * 0.28,
      timestamp: time + i * 500,
    };
    steps.push(step);
    time += step.duration;
  });
  return steps;
}

function getStepDescription(layer: LayerId, index: number): string {
  const descriptions: Record<LayerId, string[]> = {
    L5: ['评估任务复杂度与自身能力', '选择最优推理策略', '执行元认知校准', '验证策略有效性'],
    L4: ['解析任务语义', '分解子任务', '评估资源需求', '生成执行计划'],
    L3: ['检查本体约束', '执行符号推理', '融合神经信号', '验证逻辑一致性'],
    L2: ['评估进化方向', '生成代码突变', '验证变异效果', '归档进化结果'],
    L1: ['优化协作结构', '调度Agent资源', '动态路由决策', '平衡负载'],
    L0: ['调用工具链', '执行沙箱代码', '收集执行结果', '返回输出'],
  };
  return descriptions[layer][index % 4];
}

// --- 模拟任务执行 ---
export function simulateTaskExecution(request: TaskRequest): TaskResult {
  const layers: LayerId[] = determineRoutingLayers(request);
  const reasoningChain = generateReasoningChain(request.id, layers);

  const totalDuration = reasoningChain.reduce((sum, s) => sum + s.duration, 0);
  const totalTokens = reasoningChain.reduce((sum, s) => sum + s.inputTokens + s.outputTokens, 0);

  const metrics: PerformanceMetrics = {
    totalDuration,
    tokensUsed: totalTokens,
    layerTransitions: layers.length - 1,
    selfImprovementIterations: request.type === 'self_improvement' ? Math.floor(10 + Math.random() * 40) : undefined,
    crossDomainTransferScore: request.type === 'cross_domain_transfer' ? 0.4 + Math.random() * 0.3 : undefined,
  };

  return {
    taskId: request.id,
    layer: layers[layers.length - 1],
    status: Math.random() > 0.1 ? 'success' : 'partial',
    output: generateOutput(request.type),
    reasoningChain,
    performance: metrics,
    calibration: request.requireMetacognitiveMonitoring ? generateCalibration() : undefined,
    evolutionBranch: request.type === 'self_improvement' ? 'explore_meta' : undefined,
  };
}

function determineRoutingLayers(request: TaskRequest): LayerId[] {
  if (request.targetLayer) {
    const layers: LayerId[] = [];
    for (let i = parseInt(request.targetLayer[1]); i >= 0; i--) {
      layers.push(`L${i}` as LayerId);
    }
    return layers.reverse();
  }

  switch (request.type) {
    case 'self_improvement':
      return ['L5', 'L2', 'L1', 'L0'];
    case 'cross_domain_transfer':
      return ['L5', 'L4', 'L1', 'L0'];
    case 'math_reasoning':
      return ['L4', 'L3', 'L1', 'L0'];
    case 'code_review':
      return ['L3', 'L4', 'L2', 'L0'];
    case 'architecture_design':
      return ['L5', 'L4', 'L3', 'L1'];
    case 'multi_agent_orchestration':
      return ['L1', 'L0'];
    default:
      return ['L4', 'L3', 'L1', 'L0'];
  }
}

function generateOutput(type: TaskType): string {
  const outputs: Record<TaskType, string> = {
    code_generation: '生成经过优化的代码实现，通过符号验证和元认知校准确保质量。',
    code_debugging: '定位到3个关键bug，通过进化搜索找到最优修复方案。',
    code_review: '多维度代码审查完成，发现2个安全隐患、3处性能瓶颈、5项架构改进建议。',
    architecture_design: '微服务架构设计完成，包含服务拆分、容错策略、API网关设计。',
    math_reasoning: '符号推理引擎验证每一步推导，最终得到精确解。',
    data_analysis: '多维度分析完成，发现4个关键模式，置信度92%。',
    nlp_task: '语义理解 + 神经符号融合完成，输出经过本体约束验证。',
    multi_agent_orchestration: '5个Agent协作完成，OMAC优化后效率提升35%。',
    self_improvement: `完成${Math.floor(20 + Math.random() * 30)}轮自我改进，SWE-bench提升${(Math.random() * 15).toFixed(1)}%。`,
    cross_domain_transfer: `跨域迁移成功，imp@${Math.floor(40 + Math.random() * 20)}=${(0.5 + Math.random() * 0.2).toFixed(3)}`,
  };
  return outputs[type];
}

// --- 路由决策 ---
export function makeRoutingDecision(request: TaskRequest): RoutingDecision {
  const difficulty = Math.floor(3 + Math.random() * 7);
  const capability = Math.floor(5 + Math.random() * 4);

  const layerMap: Record<number, LayerId> = { 10: 'L5', 8: 'L4', 6: 'L3', 4: 'L2', 2: 'L1', 0: 'L0' };
  const selected = difficulty > capability ? 'L5' : layerMap[Math.floor(difficulty / 2) * 2] || 'L1';

  return {
    taskId: request.id,
    selectedLayer: selected,
    reasoning: `任务难度${difficulty}，系统能力${capability}。${difficulty > capability ? '激活元认知层进行策略进化。' : '常规路由处理。'}`,
    difficulty,
    estimatedCapability: capability,
    alternativeLayers: ['L4', 'L3', 'L1'],
    confidence: 0.7 + Math.random() * 0.25,
  };
}

// --- 有状态模拟（保持时序连续性与收敛性） ---

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function drift(current: number, lo: number, hi: number, maxDelta: number): number {
  const delta = (Math.random() - 0.5) * 2 * maxDelta;
  return clamp(current + delta, lo, hi);
}

const _persistentArchive = generateEvolutionArchive();

const _persistentMemory: MemorySystem = (() => {
  const entries: MemoryEntry[] = [];
  const types: MemoryEntry['type'][] = ['episodic', 'semantic', 'procedural'];
  const labels = ['Code pattern', 'Reasoning strategy', 'Collaboration protocol', 'Error pattern', 'Success heuristic'];
  for (let i = 0; i < 15; i++) {
    entries.push({
      id: `mem_${i}`,
      type: types[i % 3],
      content: `Memory entry ${i}: ${labels[i % labels.length]} #${10 + i * 7}`,
      embedding: Array.from({ length: 128 }, () => Math.random()),
      timestamp: Date.now() - (15 - i) * 3600000,
      accessCount: 5 + i * 3,
      relevance: 0.5 + (i / 30),
    });
  }
  return {
    episodic: entries.filter(e => e.type === 'episodic'),
    semantic: entries.filter(e => e.type === 'semantic'),
    procedural: entries.filter(e => e.type === 'procedural'),
  };
})();

const _persistentSafety: SafetyEvent[] = [
  { id: 'sev_001', severity: 'high', type: 'self_modification', description: 'L2层DGM引擎产生未验证的Agent变异', layer: 'L2', timestamp: Date.now() - 3600000, resolved: false },
  { id: 'sev_002', severity: 'medium', type: 'ontology_violation', description: '输出违反Policy #7约束', layer: 'L3', timestamp: Date.now() - 7200000, resolved: true },
  { id: 'sev_003', severity: 'low', type: 'sandbox_breach', description: '沙箱执行超时', layer: 'L0', timestamp: Date.now() - 1800000, resolved: true },
  { id: 'sev_004', severity: 'critical', type: 'unauthorized_access', description: '检测到未授权的元认知层修改尝试', layer: 'L5', timestamp: Date.now() - 900000, resolved: false },
  { id: 'sev_005', severity: 'medium', type: 'self_modification', description: 'Agent自我修改超出安全阈值', layer: 'L2', timestamp: Date.now() - 5400000, resolved: true },
];

const _simState = {
  throughput: 60,
  avgLatency: 180,
  errorRate: 0.035,
  activeTasks: 12,
  queuedTasks: 5,
  engineLoads: Object.fromEntries(
    LAYER_DEFINITIONS.flatMap(l => l.engines.map(e => [e.id, e.loadFactor]))
  ) as Record<string, number>,
  layerMetrics: LAYER_DEFINITIONS.map(layer => ({
    layerId: layer.id as LayerId,
    layerName: layer.name,
    tasksProcessed: 200 + LAYER_DEFINITIONS.indexOf(layer) * 30,
    avgLatency: 80 + LAYER_DEFINITIONS.indexOf(layer) * 15,
    successRate: 0.92 - LAYER_DEFINITIONS.indexOf(layer) * 0.01,
    engineUtilization: 0.45 + LAYER_DEFINITIONS.indexOf(layer) * 0.03,
    activeEngines: layer.engines.filter(e => e.status === 'running').length,
  })),
  evolutionBestScore: _persistentArchive.agents.reduce((a, b) => a.performance > b.performance ? a : b).performance,
  improvementRate: 0.015,
  activeMutations: 5,
  convergenceStatus: 'exploring' as EvolutionStats['convergenceStatus'],
  tickCount: 0,
};

const _recentTasks: TaskResult[] = (() => {
  const taskTypes: TaskType[] = ['code_generation', 'math_reasoning', 'self_improvement', 'data_analysis', 'multi_agent_orchestration', 'cross_domain_transfer'];
  const tasks: TaskResult[] = [];
  for (let i = 0; i < 10; i++) {
    tasks.push(simulateTaskExecution({
      id: `task_init_${i}`,
      type: taskTypes[i % taskTypes.length],
      query: `Initial task ${i}`,
      requireMetacognitiveMonitoring: i % 3 === 0,
    }));
  }
  return tasks;
})();

function tickSimState(): void {
  const s = _simState;
  s.tickCount++;

  s.throughput = Math.round(drift(s.throughput, 35, 85, 3));
  s.avgLatency = Math.round(drift(s.avgLatency, 80, 350, 8));
  s.errorRate = parseFloat(drift(s.errorRate, 0.01, 0.06, 0.003).toFixed(4));
  s.activeTasks = Math.round(drift(s.activeTasks, 3, 25, 1.5));
  s.queuedTasks = Math.round(drift(s.queuedTasks, 0, 15, 1));

  for (const key of Object.keys(s.engineLoads)) {
    s.engineLoads[key] = parseFloat(drift(s.engineLoads[key], 0.1, 0.9, 0.04).toFixed(3));
  }

  for (const m of s.layerMetrics) {
    m.tasksProcessed += Math.round(s.throughput / 6);
    m.avgLatency = Math.round(drift(m.avgLatency, 20, 300, 5));
    m.successRate = parseFloat(drift(m.successRate, 0.80, 0.99, 0.005).toFixed(4));
    m.engineUtilization = parseFloat(drift(m.engineUtilization, 0.15, 0.85, 0.02).toFixed(3));
  }

  s.evolutionBestScore = parseFloat(drift(s.evolutionBestScore, 0.4, 0.85, 0.003).toFixed(4));
  s.improvementRate = parseFloat(drift(s.improvementRate, 0.005, 0.03, 0.001).toFixed(4));
  s.activeMutations = Math.round(drift(s.activeMutations, 1, 12, 0.8));

  if (s.tickCount > 60 && s.convergenceStatus === 'exploring') {
    s.convergenceStatus = 'converging';
  }
  if (s.tickCount > 120 && s.convergenceStatus === 'converging') {
    s.convergenceStatus = 'converged';
  }
}

export function getSystemState(): SystemState {
  const statuses: Record<LayerId, EngineDefinition[]> = {} as Record<LayerId, EngineDefinition[]>;
  LAYER_DEFINITIONS.forEach(layer => {
    statuses[layer.id] = layer.engines.map(e => ({
      ...e,
      loadFactor: _simState.engineLoads[e.id] ?? e.loadFactor,
    }));
  });

  return {
    status: 'running',
    activeLayers: ['L0', 'L1', 'L2', 'L3', 'L4', 'L5'],
    engineStatuses: statuses,
    throughput: _simState.throughput,
    avgLatency: _simState.avgLatency,
    errorRate: _simState.errorRate,
    activeTasks: _simState.activeTasks,
    queuedTasks: _simState.queuedTasks,
    evolutionArchive: _persistentArchive,
    ontologyConstraints: [
      { entity: 'Agent', rule: '所有Agent必须经过沙箱验证', priority: 10, enforced: true },
      { entity: 'Policy', rule: '元认知修改需人类审核', priority: 9, enforced: true },
      { entity: 'Confidence', rule: '置信度<0.6触发重试', priority: 7, enforced: true },
      { entity: 'Outcome', rule: '输出需通过本体验证', priority: 8, enforced: true },
    ],
  };
}

export function getMemorySystem(): MemorySystem {
  return _persistentMemory;
}

export function getSafetyEvents(): SafetyEvent[] {
  return _persistentSafety;
}

export function getDashboardData(): DashboardData {
  tickSimState();

  const systemState = getSystemState();

  return {
    systemState,
    recentTasks: _recentTasks,
    memorySystem: _persistentMemory,
    safetyEvents: _persistentSafety,
    layerMetrics: _simState.layerMetrics.map(m => ({ ...m })),
    evolutionStats: {
      totalAgents: _persistentArchive.agents.length,
      totalBranches: _persistentArchive.branches.length,
      currentBestScore: _simState.evolutionBestScore,
      improvementRate: _simState.improvementRate,
      activeMutations: _simState.activeMutations,
      convergenceStatus: _simState.convergenceStatus,
    },
  };
}

// --- 获取层定义 ---
export function getLayerDefinitions(): LayerDefinition[] {
  return LAYER_DEFINITIONS;
}

// --- 持续模拟引擎 ---
export class MoreV3Engine {
  private state: SystemState;
  private listeners: Set<(data: DashboardData) => void> = new Set();
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private useRealAPI: boolean = false;
  private apiBaseUrl: string = import.meta.env.VITE_API_BASE || 'http://localhost:8001';

  constructor() {
    this.state = getSystemState();
  }

  setRealAPIMode(enabled: boolean, baseUrl?: string) {
    this.useRealAPI = enabled;
    if (baseUrl) {
      this.apiBaseUrl = baseUrl;
    }
  }

  async executeTaskReal(request: TaskRequest): Promise<TaskResult> {
    if (!this.useRealAPI) {
      return simulateTaskExecution(request);
    }

    try {
      const response = await fetch(`${this.apiBaseUrl}/api/tasks/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: request.type,
          query: request.query,
          context: request.context,
          require_metacognitive_monitoring: request.requireMetacognitiveMonitoring,
        }),
      });

      if (!response.ok) {
        console.warn('API call failed, falling back to simulation');
        return simulateTaskExecution(request);
      }

      const result = await response.json();

      return {
        taskId: result.task_id,
        layer: result.layer,
        status: result.status,
        output: result.output,
        reasoningChain: result.reasoning_chain.map((step: any) => ({
          id: step.id,
          layer: step.layer as LayerId,
          description: step.description,
          duration: step.duration,
          inputTokens: step.input_tokens,
          outputTokens: step.output_tokens,
          confidence: step.confidence,
          timestamp: step.timestamp,
        })),
        performance: {
          totalDuration: result.performance.total_duration,
          tokensUsed: result.performance.tokens_used,
          layerTransitions: result.performance.layer_transitions,
        },
        calibration: result.calibration ? {
          confidence: result.calibration.confidence,
          accuracy: result.calibration.accuracy,
          alignment: result.calibration.alignment,
          history: result.calibration.history || [],
        } : undefined,
      };
    } catch (error) {
      console.warn('Real API execution failed, falling back to simulation:', error);
      return simulateTaskExecution(request);
    }
  }

  startSimulation(intervalMs = 3000) {
    this.intervalId = setInterval(async () => {
      let data: DashboardData;

      if (this.useRealAPI) {
        try {
          const response = await fetch(`${this.apiBaseUrl}/api/tasks/history?limit=10`);
          if (response.ok) {
            const historyResult = await response.json();
            const systemResponse = await fetch(`${this.apiBaseUrl}/api/system/state`);
            if (systemResponse.ok) {
              const systemState = await systemResponse.json();
              data = getDashboardData();
              data.recentTasks = historyResult.tasks || [];
              data.systemState = {
                ...data.systemState,
                throughput: systemState.throughput || data.systemState.throughput,
                avgLatency: systemState.avg_latency || data.systemState.avgLatency,
                activeTasks: systemState.active_tasks || data.systemState.activeTasks,
                queuedTasks: systemState.queued_tasks || data.systemState.queuedTasks,
              };
            } else {
              data = getDashboardData();
            }
          } else {
            data = getDashboardData();
          }
        } catch {
          data = getDashboardData();
        }
      } else {
        data = getDashboardData();
      }

      this.state = data.systemState;
      this.listeners.forEach(fn => fn(data));
    }, intervalMs);
  }

  stopSimulation() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  onUpdate(fn: (data: DashboardData) => void) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  async executeTask(request: TaskRequest): Promise<TaskResult> {
    if (this.useRealAPI) {
      return this.executeTaskReal(request);
    }
    return simulateTaskExecution(request);
  }

  getState(): SystemState {
    return this.state;
  }

  isRealAPIMode(): boolean {
    return this.useRealAPI;
  }

  async healthCheck(): Promise<{ status: string; message: string } | null> {
    if (!this.useRealAPI) {
      return { status: 'simulated', message: 'Running in simulation mode' };
    }

    try {
      const response = await fetch(`${this.apiBaseUrl}/api/health`);
      if (response.ok) {
        return response.json();
      }
      return null;
    } catch {
      return null;
    }
  }
}

export const moreEngine = new MoreV3Engine();
