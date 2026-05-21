// ============================================================
// MoRE v3.0 — 核心类型定义
// ============================================================

/** 架构层级枚举 */
export type LayerId = 'L0' | 'L1' | 'L2' | 'L3' | 'L4' | 'L5';

/** 引擎状态 */
export type EngineStatus = 'idle' | 'running' | 'paused' | 'error' | 'evolving';

/** 任务类型 */
export type TaskType = 
  | 'code_generation' 
  | 'code_debugging' 
  | 'code_review'
  | 'architecture_design'
  | 'math_reasoning' 
  | 'data_analysis'
  | 'nlp_task'
  | 'multi_agent_orchestration'
  | 'self_improvement'
  | 'cross_domain_transfer';

/** 推理模式 */
export type ReasoningMode = 
  | 'neural'        // 纯神经网络推理
  | 'symbolic'      // 纯符号推理
  | 'neuro_symbolic' // 神经符号融合
  | 'metacognitive' // 元认知推理
  | 'evolutionary'  // 进化推理
  | 'collaborative'; // 协作推理

/** 元认知校准状态 */
export interface MetacognitiveCalibration {
  confidence: number;      // 置信度 (0-1)
  accuracy: number;        // 准确度 (0-1)
  alignment: number;       // 对齐度 (0-1)
  history: CalibrationPoint[];
}

export interface CalibrationPoint {
  timestamp: number;
  confidence: number;
  actualAccuracy: number;
}

/** 本体实体 (AOW标准) */
export type OntologyEntity = 
  | 'Agent' 
  | 'Skill' 
  | 'Intent' 
  | 'Context' 
  | 'Policy' 
  | 'Memory' 
  | 'Confidence' 
  | 'Outcome';

/** 本体约束 */
export interface OntologyConstraint {
  entity: OntologyEntity;
  rule: string;
  priority: number;  // 1-10
  enforced: boolean;
}

/** 任务请求 */
export interface TaskRequest {
  id: string;
  type: TaskType;
  query: string;
  context?: Record<string, unknown>;
  constraints?: OntologyConstraint[];
  requireMetacognitiveMonitoring?: boolean;
  targetLayer?: LayerId;
}

/** 任务结果 */
export interface TaskResult {
  taskId: string;
  layer: LayerId;
  status: 'success' | 'partial' | 'failed';
  output: string;
  reasoningChain: ReasoningStep[];
  performance: PerformanceMetrics;
  calibration?: MetacognitiveCalibration;
  evolutionBranch?: string; // DGM进化分支ID
}

/** 推理步骤 */
export interface ReasoningStep {
  id: number;
  layer: LayerId;
  description: string;
  duration: number; // ms
  inputTokens: number;
  outputTokens: number;
  confidence: number;
  timestamp: number;
}

/** 性能指标 */
export interface PerformanceMetrics {
  totalDuration: number;   // ms
  tokensUsed: number;
  layerTransitions: number;
  selfImprovementIterations?: number;
  crossDomainTransferScore?: number;
}

/** DGM进化档案 */
export interface EvolutionArchive {
  agents: EvolvedAgent[];
  branches: EvolutionBranch[];
  currentBest: string; // agent ID
  archiveSize: number;
  maxArchiveSize: number;
}

export interface EvolvedAgent {
  id: string;
  parentId?: string;
  generation: number;
  code: string;
  performance: number; // SWE-bench score etc.
  mutations: Mutation[];
  createdAt: number;
  branch: string;
}

export interface Mutation {
  type: 'code_change' | 'strategy_change' | 'parameter_tune' | 'architecture_change';
  description: string;
  diff: string;
  verified: boolean;
}

export interface EvolutionBranch {
  id: string;
  name: string;
  rootAgentId: string;
  agentCount: number;
  bestPerformance: number;
  isActive: boolean;
}

/** 六层架构定义 */
export interface LayerDefinition {
  id: LayerId;
  name: string;
  englishName: string;
  description: string;
  features: string[];
  color: string;
  engines: EngineDefinition[];
  inputTypes: string[];
  outputTypes: string[];
}

export interface EngineDefinition {
  id: string;
  name: string;
  description: string;
  status: EngineStatus;
  capabilities: string[];
  loadFactor: number; // 0-1
}

/** 路由决策 */
export interface RoutingDecision {
  taskId: string;
  selectedLayer: LayerId;
  reasoning: string;
  difficulty: number;    // 1-10
  estimatedCapability: number; // 1-10
  alternativeLayers: LayerId[];
  confidence: number;
}

/** 系统状态 */
export interface SystemState {
  status: 'initializing' | 'running' | 'degraded' | 'maintenance';
  activeLayers: LayerId[];
  engineStatuses: Record<LayerId, EngineDefinition[]>;
  throughput: number; // tasks/min
  avgLatency: number; // ms
  errorRate: number;  // 0-1
  activeTasks: number;
  queuedTasks: number;
  evolutionArchive: EvolutionArchive;
  ontologyConstraints: OntologyConstraint[];
}

/** 记忆系统 */
export interface MemorySystem {
  episodic: MemoryEntry[];   // 情景记忆
  semantic: MemoryEntry[];   // 语义记忆
  procedural: MemoryEntry[]; // 程序记忆
}

export interface MemoryEntry {
  id: string;
  type: 'episodic' | 'semantic' | 'procedural';
  content: string;
  embedding: number[];
  timestamp: number;
  accessCount: number;
  relevance: number; // 0-1
}

/** 安全事件 */
export interface SafetyEvent {
  id: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  type: 'sandbox_breach' | 'ontology_violation' | 'self_modification' | 'unauthorized_access';
  description: string;
  layer: LayerId;
  timestamp: number;
  resolved: boolean;
}

/** 仪表盘数据 */
export interface DashboardData {
  systemState: SystemState;
  recentTasks: TaskResult[];
  memorySystem: MemorySystem;
  safetyEvents: SafetyEvent[];
  layerMetrics: LayerMetrics[];
  evolutionStats: EvolutionStats;
}

export interface LayerMetrics {
  layerId: LayerId;
  layerName: string;
  tasksProcessed: number;
  avgLatency: number;
  successRate: number;
  engineUtilization: number;
  activeEngines: number;
}

export interface EvolutionStats {
  totalAgents: number;
  totalBranches: number;
  currentBestScore: number;
  improvementRate: number; // per iteration
  activeMutations: number;
  convergenceStatus: 'exploring' | 'converging' | 'converged' | 'diverging';
}
