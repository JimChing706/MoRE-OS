import { useState, useMemo, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Separator } from '@/components/ui/separator';

import { moreEngine } from '@/core/moreEngine';
import { useApiHealth } from '@/hooks/useApiHealth';
import { formatDuration, formatTokens } from '@/lib/format';
import type { TaskRequest, TaskResult, TaskType, LayerId, ReasoningStep } from '@/types/morev3';
import {
  Code, Bug, Calculator, BarChart3, MessageSquare,
  Users, Sparkles, ArrowRightLeft, Clock,
  CheckCircle2, AlertCircle, Terminal,
  GitPullRequest, Layers, Info, ArrowDown, ArrowRight,
  Zap, Brain, Network, Cpu, ChevronDown, ChevronUp, Activity,
  List, Grid3X3, ArrowUp, LayoutGrid, GitBranch,
  Timer, Hash, Percent, TrendingUp, BarChart2, Contrast
} from 'lucide-react';

const TASK_PRESETS: { type: TaskType; label: string; icon: React.ReactNode; query: string; description: string; category: string; layers: LayerId[]; features: string[] }[] = [
  { type: 'code_generation', label: '代码生成', icon: <Code className="w-4 h-4" />, query: 'Generate a Python function to optimize supply chain logistics with dynamic programming', description: '认知→符号→编排→执行', category: '开发', layers: ['L4', 'L3', 'L1', 'L0'], features: ['语义解析', '符号推理', '编排调度', '代码执行'] },
  { type: 'code_debugging', label: '代码调试', icon: <Bug className="w-4 h-4" />, query: 'Debug the memory leak in the async worker pool with detailed root cause analysis', description: '认知→符号→编排→执行', category: '开发', layers: ['L4', 'L3', 'L1', 'L0'], features: ['根因分析', '符号验证', '编排定位', '修复执行'] },
  { type: 'code_review', label: '代码审查', icon: <GitPullRequest className="w-4 h-4" />, query: 'Review this code for security vulnerabilities, performance issues, and architectural improvements', description: '认知→符号→编排→执行', category: '开发', layers: ['L4', 'L3', 'L1', 'L0'], features: ['语义理解', '安全扫描', '协作审查', '改进输出'] },
  { type: 'code_testing', label: '代码测试', icon: <CheckCircle2 className="w-4 h-4" />, query: 'Generate and run unit tests for the given Python module with coverage analysis', description: '认知→符号→编排→执行', category: '开发', layers: ['L4', 'L3', 'L1', 'L0'], features: ['测试生成', '符号验证', '沙箱执行', '覆盖率报告'] },
  { type: 'architecture_design', label: '架构设计', icon: <Layers className="w-4 h-4" />, query: 'Design a scalable microservices architecture for an e-commerce platform with service mesh', description: '元认知→认知→符号→编排→执行', category: '开发', layers: ['L5', 'L4', 'L3', 'L1', 'L0'], features: ['需求分析', '元认知校准', '约束验证', '服务拆分', '架构输出'] },
  { type: 'math_reasoning', label: '数学推理', icon: <Calculator className="w-4 h-4" />, query: 'Prove that every prime > 3 is of form 6k±1 with formal verification', description: 'NSPA-AI符号推理验证', category: '推理', layers: ['L4', 'L3', 'L0'], features: ['形式化证明', '约束验证', '推理链'] },
  { type: 'data_analysis', label: '数据分析', icon: <BarChart3 className="w-4 h-4" />, query: 'Analyze customer churn patterns in the Q1 dataset with predictive modeling', description: '多Agent协作分析', category: '推理', layers: ['L1', 'L4', 'L0'], features: ['数据聚合', '模式识别', '预测建模'] },
  { type: 'nlp_task', label: 'NLP任务', icon: <MessageSquare className="w-4 h-4" />, query: 'Extract named entities and relations from legal documents with context awareness', description: '神经符号融合', category: '推理', layers: ['L4', 'L3', 'L0'], features: ['实体识别', '关系抽取', '上下文融合'] },
  { type: 'multi_agent_orchestration', label: 'Agent编排', icon: <Users className="w-4 h-4" />, query: 'Coordinate 5 agents to build a microservice architecture with optimal task distribution', description: 'OMAC优化编排', category: '协作', layers: ['L1', 'L4', 'L2'], features: ['任务分解', '负载均衡', '协作优化'] },
  { type: 'self_improvement', label: '自我改进', icon: <Sparkles className="w-4 h-4" />, query: 'Evolve the reasoning strategy for code review tasks with performance metrics', description: 'DGM + HyperAgents', category: '协作', layers: ['L5', 'L2', 'L4'], features: ['策略学习', '性能迭代', '自适应'] },
  { type: 'cross_domain_transfer', label: '跨域迁移', icon: <ArrowRightLeft className="w-4 h-4" />, query: 'Transfer math proof strategies to algorithm design with generalization', description: '元认知跨域迁移', category: '协作', layers: ['L5', 'L4', 'L3'], features: ['知识迁移', '泛化验证', '领域适配'] },
];

const layerColors: Record<LayerId, string> = {
  L5: '#FF6F00', L4: '#FF8F00', L3: '#FFA000', L2: '#FFB300', L1: '#FFC107', L0: '#FFD54F',
};

const layerNames: Record<LayerId, string> = {
  L5: '元认知层', L4: '认知层', L3: '符号推理层', L2: '神经进化层', L1: '协作编排层', L0: '执行层',
};

const layerIcons: Record<LayerId, React.ReactNode> = {
  L5: <Brain className="w-4 h-4" />,
  L4: <Zap className="w-4 h-4" />,
  L3: <Network className="w-4 h-4" />,
  L2: <Activity className="w-4 h-4" />,
  L1: <Layers className="w-4 h-4" />,
  L0: <Cpu className="w-4 h-4" />,
};

const layerDescriptions: Record<LayerId, string[]> = {
  L5: ['评估任务复杂度与自身能力', '选择最优推理策略', '执行元认知校准', '验证策略有效性'],
  L4: ['解析任务语义', '分解子任务', '评估资源需求', '生成执行计划'],
  L3: ['检查本体约束', '执行符号推理', '融合神经信号', '验证逻辑一致性'],
  L2: ['评估进化方向', '生成代码突变', '验证变异效果', '归档进化结果'],
  L1: ['优化协作结构', '调度Agent资源', '动态路由决策', '平衡负载'],
  L0: ['调用工具链', '执行沙箱代码', '收集执行结果', '返回输出'],
};

const chainViewConfig = {
  title: '推理链视图',
  description: '按时间顺序展示各层的执行流程，显示层间依赖和数据流动',
  features: [
    { name: '时序展开', icon: <Timer className="w-3 h-3" />, detail: '垂直时间线显示执行顺序' },
    { name: '层间依赖', icon: <GitBranch className="w-3 h-3" />, detail: '展示层与层之间的数据传递' },
    { name: '数据流动', icon: <ArrowRight className="w-3 h-3" />, detail: '追踪输入输出的流向' },
    { name: '进度跟踪', icon: <TrendingUp className="w-3 h-3" />, detail: '实时显示各层的执行进度' },
  ],
  icon: <List className="w-4 h-4" />,
  color: '#FF6F00',
  badge: '时序模式',
};

const cardsViewConfig = {
  title: '卡片视图',
  description: '以网格形式展示各层的关键指标和性能数据，便于快速对比',
  features: [
    { name: '网格布局', icon: <Grid3X3 className="w-3 h-3" />, detail: '3x2 网格展示各层' },
    { name: '指标对比', icon: <BarChart2 className="w-3 h-3" />, detail: '并列对比延迟、Token、置信度' },
    { name: '性能概览', icon: <LayoutGrid className="w-3 h-3" />, detail: '一眼看清整体性能分布' },
    { name: '快速定位', icon: <Contrast className="w-3 h-3" />, detail: '通过颜色快速识别瓶颈层' },
  ],
  icon: <Grid3X3 className="w-4 h-4" />,
  color: '#3B82F6',
  badge: '对比模式',
};

export function TaskPanel() {
  const [results, setResults] = useState<TaskResult[]>([]);
  const [executing, setExecuting] = useState<string | null>(null);
  const [execError, setExecError] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<TaskResult | null>(null);
  const [viewMode, setViewMode] = useState<'cards' | 'chain'>('chain');
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());
  const { online } = useApiHealth();

  const categories = [...new Set(TASK_PRESETS.map(p => p.category))];

  const toggleStep = (stepId: number) => {
    setExpandedSteps(prev => {
      const newSet = new Set(prev);
      if (newSet.has(stepId)) {
        newSet.delete(stepId);
      } else {
        newSet.add(stepId);
      }
      return newSet;
    });
  };

  const executeTask = async (preset: typeof TASK_PRESETS[0]) => {
    const taskId = `task_${Date.now()}`;
    setExecuting(taskId);
    setExecError(null);

    const request: TaskRequest = {
      id: taskId,
      type: preset.type,
      query: preset.query,
      requireMetacognitiveMonitoring: preset.type === 'self_improvement' || preset.type === 'cross_domain_transfer',
    };

    try {
      await new Promise(r => setTimeout(r, 300 + Math.random() * 500));
      const result = await moreEngine.executeTask(request);

      setResults(prev => [result, ...prev].slice(0, 20));
      setSelectedResult(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setExecError(msg);
      console.error('Task execution failed:', err);
    } finally {
      setExecuting(null);
    }
  };

  const stats = useMemo(() => {
    if (!selectedResult) return null;
    const chain = selectedResult.reasoningChain;
    return {
      totalDuration: chain.reduce((sum, s) => sum + s.duration, 0),
      avgDuration: chain.length > 0 ? Math.round(chain.reduce((sum, s) => sum + s.duration, 0) / chain.length) : 0,
      totalTokens: chain.reduce((sum, s) => sum + s.inputTokens + s.outputTokens, 0),
      avgConfidence: chain.length > 0 ? (chain.reduce((sum, s) => sum + s.confidence, 0) / chain.length) : 0,
      maxDuration: Math.max(...chain.map(s => s.duration)),
      minDuration: Math.min(...chain.map(s => s.duration)),
    };
  }, [selectedResult]);

  const currentConfig = viewMode === 'chain' ? chainViewConfig : cardsViewConfig;

  return (
    <TooltipProvider>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
            <Terminal className="w-5 h-5 text-orange-600" />
            任务执行面板
          </h3>
          <div className="flex items-center gap-2">
            {online ? (
              <Badge variant="outline" className="text-xs bg-green-50 text-green-700 border-green-200 gap-1">
                <div className="w-2 h-2 rounded-full bg-green-500" /> API 已连接
              </Badge>
            ) : (
              <Badge variant="outline" className="text-xs bg-red-50 text-red-700 border-red-200 gap-1">
                <div className="w-2 h-2 rounded-full bg-red-500" /> API 离线
              </Badge>
            )}
          </div>
        </div>

        {/* 视图模式对比选择器 - 强化视觉对比 */}
        <div className="relative">
          {/* 视图模式切换按钮组 */}
          <div className="grid grid-cols-2 gap-2 mb-3">
            {/* 推理链视图选项 */}
            <div 
              className={`relative p-4 rounded-xl border-2 cursor-pointer transition-all ${
                viewMode === 'chain' 
                  ? 'border-orange-500 bg-orange-50 shadow-lg' 
                  : 'border-gray-200 bg-white hover:border-orange-300'
              }`}
              onClick={() => setViewMode('chain')}
            >
              {viewMode === 'chain' && (
                <div className="absolute -top-3 left-4">
                  <Badge className="bg-orange-500 text-white text-xs px-2 py-0.5">
                    当前选中
                  </Badge>
                </div>
              )}
              <div className="flex items-center gap-3 mb-3">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                  viewMode === 'chain' ? 'bg-orange-500 text-white' : 'bg-gray-100 text-gray-600'
                }`}>
                  <List className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-gray-800">推理链视图</h4>
                  <p className="text-xs text-gray-500">时序展开模式</p>
                </div>
              </div>
              
              {/* 特征列表 */}
              <div className="space-y-2">
                {chainViewConfig.features.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <div className="w-6 h-6 rounded bg-orange-100 flex items-center justify-center text-orange-600">
                      {f.icon}
                    </div>
                    <span className="font-medium text-gray-700">{f.name}</span>
                    <span className="text-gray-400 text-[10px]">- {f.detail}</span>
                  </div>
                ))}
              </div>
              
              {/* 预览示意 */}
              <div className="mt-3 p-2 bg-white rounded border border-gray-100">
                <div className="flex items-center gap-1">
                  <div className="w-2 h-8 bg-orange-200 rounded-full" />
                  <div className="space-y-1">
                    <div className="h-4 w-20 bg-orange-400 rounded" />
                    <div className="h-4 w-16 bg-orange-300 rounded" />
                    <div className="h-4 w-18 bg-orange-200 rounded" />
                  </div>
                </div>
              </div>
            </div>

            {/* 卡片视图选项 */}
            <div 
              className={`relative p-4 rounded-xl border-2 cursor-pointer transition-all ${
                viewMode === 'cards' 
                  ? 'border-blue-500 bg-blue-50 shadow-lg' 
                  : 'border-gray-200 bg-white hover:border-blue-300'
              }`}
              onClick={() => setViewMode('cards')}
            >
              {viewMode === 'cards' && (
                <div className="absolute -top-3 left-4">
                  <Badge className="bg-blue-500 text-white text-xs px-2 py-0.5">
                    当前选中
                  </Badge>
                </div>
              )}
              <div className="flex items-center gap-3 mb-3">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                  viewMode === 'cards' ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600'
                }`}>
                  <Grid3X3 className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-gray-800">卡片视图</h4>
                  <p className="text-xs text-gray-500">网格对比模式</p>
                </div>
              </div>
              
              {/* 特征列表 */}
              <div className="space-y-2">
                {cardsViewConfig.features.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <div className="w-6 h-6 rounded bg-blue-100 flex items-center justify-center text-blue-600">
                      {f.icon}
                    </div>
                    <span className="font-medium text-gray-700">{f.name}</span>
                    <span className="text-gray-400 text-[10px]">- {f.detail}</span>
                  </div>
                ))}
              </div>
              
              {/* 预览示意 */}
              <div className="mt-3 p-2 bg-white rounded border border-gray-100">
                <div className="grid grid-cols-3 gap-1">
                  <div className="h-6 bg-blue-400 rounded" />
                  <div className="h-6 bg-blue-300 rounded" />
                  <div className="h-6 bg-blue-200 rounded" />
                  <div className="h-6 bg-blue-300 rounded" />
                  <div className="h-6 bg-blue-200 rounded" />
                  <div className="h-6 bg-blue-100 rounded" />
                </div>
              </div>
            </div>
          </div>
          
          {/* 当前视图指示器 */}
          <div className={`flex items-center gap-2 p-3 rounded-lg ${
            viewMode === 'chain' 
              ? 'bg-gradient-to-r from-orange-50 to-amber-50 border border-orange-200' 
              : 'bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200'
          }`}>
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
              viewMode === 'chain' ? 'bg-orange-500 text-white' : 'bg-blue-500 text-white'
            }`}>
              {currentConfig.icon}
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="font-bold text-sm">{currentConfig.title}</span>
                <Badge 
                  className={`text-[10px] ${viewMode === 'chain' ? 'bg-orange-500' : 'bg-blue-500'} text-white`}
                >
                  {currentConfig.badge}
                </Badge>
              </div>
              <p className="text-xs text-gray-500 mt-0.5">{currentConfig.description}</p>
            </div>
          </div>
        </div>

        <Separator />

        {/* API offline warning */}
        {!online && (
          <div className="p-3 rounded-lg border-2 border-red-200 bg-red-50 text-sm text-red-700">
            <div className="flex items-center gap-2 mb-1">
              <AlertCircle className="w-4 h-4" />
              <span className="font-bold">API 服务不可达</span>
            </div>
            <p className="text-xs text-red-600">{'请确认 API 服务已启动 (http://localhost:8011)'}</p>
          </div>
        )}

        {/* Execution error */}
        {execError && (
          <div className="p-3 rounded-lg border-2 border-yellow-200 bg-yellow-50 text-sm text-yellow-800">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              <span className="font-bold">执行失败</span>
              <Button variant="ghost" size="sm" className="text-xs h-6" onClick={() => setExecError(null)}>关闭</Button>
            </div>
            <p className="text-xs text-yellow-700 mt-1 font-mono">{execError}</p>
          </div>
        )}

        <Tabs defaultValue={categories[0]} className="w-full">
          <TabsList className="w-full flex flex-wrap h-auto gap-1">
            {categories.map(cat => (
              <TabsTrigger key={cat} value={cat} className="text-xs">
                {cat}
              </TabsTrigger>
            ))}
          </TabsList>

          {categories.map(cat => (
            <TabsContent key={cat} value={cat} className="mt-2">
              <div className="grid grid-cols-2 gap-3">
                {TASK_PRESETS.filter(p => p.category === cat).map(preset => (
                  <div
                    key={preset.type}
                    className={`
                      relative p-3 rounded-xl border-2 cursor-pointer transition-all
                      border-gray-200 bg-white hover:border-orange-300 hover:shadow-md
                      ${executing ? 'opacity-60 pointer-events-none' : ''}
                    `}
                    onClick={() => !executing && executeTask(preset)}
                  >
                    {executing && (
                      <div className="absolute inset-0 flex items-center justify-center bg-white/50 rounded-xl z-10">
                        <div className="w-5 h-5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
                      </div>
                    )}
                    
                    {/* 头部：图标 + 标题 */}
                    <div className="flex items-start gap-2 mb-2">
                      <div className="w-9 h-9 rounded-lg bg-orange-100 flex items-center justify-center text-orange-600">
                        {preset.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-bold text-gray-800">{preset.label}</span>
                          <Badge variant="outline" className="text-[8px] h-4 px-1">{cat}</Badge>
                        </div>
                        <p className="text-[10px] text-gray-400 mt-0.5">{preset.description}</p>
                      </div>
                    </div>

                    {/* 参与的层级 */}
                    <div className="mb-2">
                      <div className="flex items-center gap-1 mb-1">
                        <Layers className="w-3 h-3 text-gray-400" />
                        <span className="text-[9px] text-gray-500">参与层</span>
                      </div>
                      <div className="flex items-center gap-1">
                        {preset.layers.map((layer, i) => (
                          <div key={layer} className="flex items-center">
                            <Badge
                              className="text-[9px] h-4 px-1 font-mono"
                              style={{ backgroundColor: layerColors[layer], color: '#fff' }}
                            >
                              {layer}
                            </Badge>
                            {i < preset.layers.length - 1 && (
                              <ArrowRight className="w-2 h-2 text-gray-300 mx-0.5" />
                            )}
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* 特性标签 */}
                    <div className="flex items-center gap-1 flex-wrap">
                      {preset.features.map((feature, i) => (
                        <Badge key={i} variant="outline" className="text-[8px] h-4 px-1 bg-gray-50">
                          {feature}
                        </Badge>
                      ))}
                    </div>

                    {/* 执行指示器 */}
                    <div className="absolute top-2 right-2 opacity-0 hover:opacity-100 transition-opacity">
                      <Zap className="w-4 h-4 text-orange-500" />
                    </div>
                  </div>
                ))}
              </div>
            </TabsContent>
          ))}
        </Tabs>

        {selectedResult && (
          <Card className={`border-2 ${viewMode === 'chain' ? 'border-orange-200' : 'border-blue-200'}`}>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-green-500" />
                  执行结果
                  <Badge variant="outline" className={`text-xs ${
                    viewMode === 'chain' ? 'bg-orange-50' : 'bg-blue-50'
                  }`}>
                    {layerNames[selectedResult.layer as LayerId]}
                  </Badge>
                </CardTitle>
                <Badge
                  variant={selectedResult.status === 'success' ? 'default' : 'secondary'}
                  className={selectedResult.status === 'success' ? 'bg-green-500' : 'bg-yellow-500'}
                >
                  {selectedResult.status === 'success' ? '成功' : '部分成功'}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className={`rounded-lg p-3 border ${
                viewMode === 'chain' 
                  ? 'bg-orange-50 border-orange-100' 
                  : 'bg-blue-50 border-blue-100'
              }`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-gray-600">任务输出</span>
                  <Badge className={`text-[10px] ${
                    viewMode === 'chain' ? 'bg-orange-100 text-orange-600' : 'bg-blue-100 text-blue-600'
                  }`}>
                    {viewMode === 'chain' ? '时序输出' : '最终输出'}
                  </Badge>
                </div>
                <p className="text-sm text-gray-700 font-mono text-xs leading-relaxed max-h-32 overflow-y-auto">
                  {selectedResult.output}
                </p>
              </div>

              {/* 性能指标卡片 */}
              {stats && (
                <div className="grid grid-cols-6 gap-2">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className={`p-2 rounded-lg text-center cursor-help border-2 ${
                        viewMode === 'chain' ? 'border-orange-100 bg-orange-50' : 'border-blue-100 bg-blue-50'
                      }`}>
                        <Clock className="w-3 h-3 mx-auto mb-1 text-orange-500" />
                        <div className="font-mono font-bold text-sm text-orange-700">{formatDuration(stats.totalDuration, 'badge')}</div>
                        <div className="text-[10px] text-orange-500">总延迟</div>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p className="text-xs">所有层执行的总耗时</p>
                    </TooltipContent>
                  </Tooltip>
                  
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="bg-green-50 p-2 rounded-lg text-center cursor-help border-2 border-green-100">
                        <Activity className="w-3 h-3 mx-auto mb-1 text-green-500" />
                        <div className="font-mono font-bold text-sm text-green-700">{formatDuration(stats.avgDuration, 'badge')}</div>
                        <div className="text-[10px] text-green-500">平均延迟</div>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p className="text-xs">每层执行的平均耗时</p>
                    </TooltipContent>
                  </Tooltip>
                  
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="bg-purple-50 p-2 rounded-lg text-center cursor-help border-2 border-purple-100">
                        <Terminal className="w-3 h-3 mx-auto mb-1 text-purple-500" />
                        <div className="font-mono font-bold text-sm text-purple-700">{stats.totalTokens}</div>
                        <div className="text-[10px] text-purple-500">总Token</div>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p className="text-xs">输入+输出token总量</p>
                    </TooltipContent>
                  </Tooltip>
                  
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="bg-orange-50 p-2 rounded-lg text-center cursor-help border-2 border-orange-100">
                        <Sparkles className="w-3 h-3 mx-auto mb-1 text-orange-500" />
                        <div className="font-mono font-bold text-sm text-orange-700">{(stats.avgConfidence * 100).toFixed(0)}%</div>
                        <div className="text-[10px] text-orange-500">平均置信</div>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p className="text-xs">各层置信度的平均值</p>
                    </TooltipContent>
                  </Tooltip>
                  
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="bg-red-50 p-2 rounded-lg text-center cursor-help border-2 border-red-100">
                        <ArrowUp className="w-3 h-3 mx-auto mb-1 text-red-500" />
                        <div className="font-mono font-bold text-sm text-red-700">{formatDuration(stats.maxDuration, 'badge')}</div>
                        <div className="text-[10px] text-red-500">最大延迟</div>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p className="text-xs">执行最慢的层耗时</p>
                    </TooltipContent>
                  </Tooltip>
                  
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="bg-cyan-50 p-2 rounded-lg text-center cursor-help border-2 border-cyan-100">
                        <ArrowDown className="w-3 h-3 mx-auto mb-1 text-cyan-500" />
                        <div className="font-mono font-bold text-sm text-cyan-700">{formatDuration(stats.minDuration, 'badge')}</div>
                        <div className="text-[10px] text-cyan-500">最小延迟</div>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p className="text-xs">执行最快的层耗时</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
              )}

              {/* 推理链可视化区域 */}
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                      viewMode === 'chain' 
                        ? 'bg-orange-500 text-white' 
                        : 'bg-blue-500 text-white'
                    }`}>
                      {viewMode === 'chain' ? <List className="w-4 h-4" /> : <Grid3X3 className="w-4 h-4" />}
                    </div>
                    <div>
                      <h4 className="text-sm font-bold text-gray-700">推理链可视化</h4>
                      <div className="flex gap-2 mt-1">
                        <Badge className={`text-[10px] ${
                          viewMode === 'chain' 
                            ? 'bg-orange-100 text-orange-600' 
                            : 'bg-blue-100 text-blue-600'
                        }`}>
                          {viewMode === 'chain' ? '时序展开 · 层间依赖' : '网格布局 · 指标对比'}
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {selectedResult.reasoningChain.length} 层
                        </Badge>
                      </div>
                    </div>
                  </div>
                  
                  <Tooltip>
                    <TooltipTrigger>
                      <Button variant="ghost" size="sm" className="text-gray-400">
                        <Info className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent className="w-64">
                      <p className="text-xs font-medium mb-1">
                        {viewMode === 'chain' ? '推理链视图说明' : '卡片视图说明'}
                      </p>
                      <p className="text-[10px] text-gray-500">
                        {viewMode === 'chain' 
                          ? '点击任意层卡片可展开查看详细指标、输入输出token和置信度变化。适合分析任务执行的完整流程和数据依赖。'
                          : '以网格形式展示各层关键指标，可快速对比各层的延迟、token消耗和置信度。适合概览性能分布和定位瓶颈层。'
                        }
                      </p>
                    </TooltipContent>
                  </Tooltip>
                </div>
                
                {viewMode === 'chain' ? (
                  <EnhancedChainView 
                    steps={selectedResult.reasoningChain} 
                    expandedSteps={expandedSteps}
                    onToggle={toggleStep}
                  />
                ) : (
                  <CardsView steps={selectedResult.reasoningChain} />
                )}
              </div>

              {selectedResult.calibration && (
                <div className={`p-3 rounded-lg border-2 ${
                  viewMode === 'chain' 
                    ? 'bg-gradient-to-r from-orange-50 to-amber-50 border-orange-200' 
                    : 'bg-gradient-to-r from-blue-50 to-indigo-50 border-blue-200'
                }`}>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-medium text-gray-700 flex items-center gap-2">
                      <Sparkles className="w-3 h-3 text-orange-500" />
                      元认知校准
                      <Badge variant="outline" className="text-[10px]">L5层</Badge>
                    </h4>
                  </div>
                  <div className="grid grid-cols-3 gap-3 text-xs">
                    <div className="bg-white/50 p-2 rounded text-center">
                      <div className="text-lg font-mono font-bold text-orange-600">
                        {(selectedResult.calibration.confidence * 100).toFixed(1)}%
                      </div>
                      <div className="text-gray-500">置信度</div>
                    </div>
                    <div className="bg-white/50 p-2 rounded text-center">
                      <div className="text-lg font-mono font-bold text-green-600">
                        {(selectedResult.calibration.accuracy * 100).toFixed(1)}%
                      </div>
                      <div className="text-gray-500">准确度</div>
                    </div>
                    <div className="bg-white/50 p-2 rounded text-center">
                      <div className="text-lg font-mono font-bold text-blue-600">
                        {(selectedResult.calibration.alignment * 100).toFixed(1)}%
                      </div>
                      <div className="text-gray-500">对齐度</div>
                    </div>
                  </div>
                  <svg viewBox="0 0 100 30" className="w-full h-8 mt-2">
                    {selectedResult.calibration.history.map((pt, i, arr) => {
                      if (i === 0) return null;
                      const x1 = ((i - 1) / arr.length) * 100;
                      const x2 = (i / arr.length) * 100;
                      const y1 = 30 - pt.confidence * 30;
                      const y2 = 30 - arr[i - 1].confidence * 30;
                      return (
                        <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#FF6F00" strokeWidth="1.5" opacity="0.8" />
                      );
                    })}
                    {selectedResult.calibration.history.map((pt, i, arr) => {
                      const x = (i / arr.length) * 100;
                      const y = 30 - pt.actualAccuracy * 30;
                      return (
                        <circle key={`a-${i}`} cx={x} cy={y} r="1.5" fill="#4CAF50" opacity="0.6" />
                      );
                    })}
                  </svg>
                  <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                    <span>置信度趋势</span>
                    <span>准确度趋势</span>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {results.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Clock className="w-4 h-4" />
                执行历史 ({results.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-48">
                <div className="space-y-1">
                  {results.map(r => (
                    <div
                      key={r.taskId}
                      onClick={() => setSelectedResult(r)}
                      className={`flex items-center gap-2 p-2 rounded cursor-pointer text-xs transition-all ${
                        selectedResult?.taskId === r.taskId 
                          ? 'bg-orange-50 border border-orange-200' 
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      {r.status === 'success' ?
                        <CheckCircle2 className="w-3 h-3 text-green-500 flex-shrink-0" /> :
                        <AlertCircle className="w-3 h-3 text-yellow-500 flex-shrink-0" />
                      }
                      <Badge
                        className="text-[10px] flex-shrink-0 font-bold"
                        style={{ backgroundColor: layerColors[r.layer as LayerId], color: '#fff' }}
                      >
                        {r.layer}
                      </Badge>
                      <span className="flex-1 truncate text-gray-600">{r.output.slice(0, 50)}...</span>
                      <span className="text-gray-400 flex-shrink-0 font-mono">{formatDuration(r.performance.totalDuration, 'compact')}</span>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        )}
      </div>
    </TooltipProvider>
  );
}

interface EnhancedChainViewProps {
  steps: ReasoningStep[];
  expandedSteps: Set<number>;
  onToggle: (id: number) => void;
}

function EnhancedChainView({ steps, expandedSteps, onToggle }: EnhancedChainViewProps) {
  return (
    <div className="relative">
      {/* 时间线主轴 - 橙色主题 */}
      <div className="absolute left-4 top-0 bottom-0 w-1 bg-gradient-to-b from-orange-500 via-amber-400 to-yellow-300 rounded-full" />
      
      <div className="space-y-4 pl-10">
        {steps.map((step, i) => {
          const color = layerColors[step.layer as LayerId];
          const isExpanded = expandedSteps.has(step.id);
          const progress = ((i + 1) / steps.length) * 100;
          const descriptions = layerDescriptions[step.layer as LayerId] || [];
          
          return (
            <div key={step.id} className="relative">
              {/* 层节点指示器 */}
              <div
                className="absolute -left-9 w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-lg border-2 border-white"
                style={{ backgroundColor: color, boxShadow: `0 0 12px ${color}60` }}
              >
                {step.layer}
              </div>
              
              {/* 层卡片 - 橙色主题 */}
              <div 
                className={`rounded-lg border-2 transition-all ${
                  isExpanded 
                    ? 'border-orange-400 shadow-lg bg-gradient-to-r from-orange-50 to-amber-50' 
                    : 'border-orange-100 bg-gradient-to-r from-gray-50 to-white hover:border-orange-200'
                }`}
              >
                <div 
                  className="p-3 cursor-pointer"
                  onClick={() => onToggle(step.id)}
                >
                  {/* 标题行 */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <div 
                        className="w-7 h-7 rounded flex items-center justify-center text-white"
                        style={{ backgroundColor: color }}
                      >
                        {layerIcons[step.layer as LayerId]}
                      </div>
                      <div>
                        <span className="text-sm font-bold text-gray-800">{layerNames[step.layer as LayerId]}</span>
                        <span className="text-xs text-gray-400 ml-2">#{step.id}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {isExpanded ? (
                        <ChevronUp className="w-4 h-4 text-orange-500" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-gray-400" />
                      )}
                    </div>
                  </div>
                  
                  {/* 操作描述 */}
                  <p className="text-xs text-gray-600 mb-2">
                    <span className="text-orange-500 font-medium">▶</span> {descriptions[i % descriptions.length] || step.description}
                  </p>
                  
                  {/* 快捷指标行 - 橙色主题 */}
                  <div className="flex items-center gap-2">
                    <span className="flex items-center gap-1 bg-orange-100 px-2 py-1 rounded text-[10px]">
                      <Timer className="w-3 h-3 text-orange-600" />
                      <span className="font-mono font-bold text-orange-700">{formatDuration(step.duration, 'badge')}</span>
                    </span>
                    <span className="flex items-center gap-1 bg-green-100 px-2 py-1 rounded text-[10px]">
                      <Hash className="w-3 h-3 text-green-600" />
                      <span className="font-mono text-green-700">{formatTokens(step.inputTokens)}</span>
                    </span>
                    <span className="flex items-center gap-1 bg-purple-100 px-2 py-1 rounded text-[10px]">
                      <ArrowRight className="w-3 h-3 text-purple-600" />
                      <span className="font-mono text-purple-700">{formatTokens(step.outputTokens)}</span>
                    </span>
                    <span className="flex items-center gap-1 bg-yellow-100 px-2 py-1 rounded text-[10px]">
                      <Percent className="w-3 h-3 text-yellow-600" />
                      <span className="font-mono font-bold text-yellow-700">{(step.confidence * 100).toFixed(0)}%</span>
                    </span>
                  </div>
                  
                  {/* 进度条 - 橙色主题 */}
                  <div className="mt-2 h-2 bg-orange-100 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${progress}%`, backgroundColor: color }}
                    />
                  </div>
                </div>
                
                {/* 展开详情 */}
                {isExpanded && (
                  <div className="px-3 pb-3 border-t border-orange-100 pt-2">
                    <div className="grid grid-cols-3 gap-2 text-[10px]">
                      <div className="bg-orange-50 p-2 rounded border border-orange-100">
                        <div className="text-gray-500 mb-1 flex items-center gap-1">
                          <Hash className="w-3 h-3" /> 输入Token
                        </div>
                        <div className="font-mono font-bold text-orange-700">{step.inputTokens.toLocaleString()}</div>
                      </div>
                      <div className="bg-purple-50 p-2 rounded border border-purple-100">
                        <div className="text-gray-500 mb-1 flex items-center gap-1">
                          <ArrowRight className="w-3 h-3" /> 输出Token
                        </div>
                        <div className="font-mono font-bold text-purple-700">{step.outputTokens.toLocaleString()}</div>
                      </div>
                      <div className="bg-yellow-50 p-2 rounded border border-yellow-100">
                        <div className="text-gray-500 mb-1 flex items-center gap-1">
                          <Timer className="w-3 h-3" /> 执行延迟
                        </div>
                        <div className="font-mono font-bold text-yellow-700">{formatDuration(step.duration, 'full')}</div>
                      </div>
                    </div>
                    
                    {/* 层间依赖箭头 */}
                    {i < steps.length - 1 && (
                      <div className="mt-2 flex items-center gap-1 text-[10px] text-orange-500 bg-orange-50 px-2 py-1 rounded">
                        <ArrowRight className="w-3 h-3" />
                        <span>数据传递至 <strong>{steps[i + 1].layer}</strong> 层</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CardsView({ steps }: { steps: ReasoningStep[] }) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {steps.map(step => {
        const color = layerColors[step.layer as LayerId];
        const descriptions = layerDescriptions[step.layer as LayerId] || [];
        
        return (
          <div
            key={step.id}
            className="rounded-xl p-4 border-2 transition-all hover:shadow-lg hover:scale-[1.02]"
            style={{ 
              borderColor: color, 
              backgroundColor: `${color}08`,
            }}
          >
            {/* 头部 - 蓝色主题 */}
            <div className="flex items-center justify-between mb-3">
              <div 
                className="w-10 h-10 rounded-full flex items-center justify-center text-white text-sm font-bold shadow-lg"
                style={{ backgroundColor: color }}
              >
                {step.layer}
              </div>
              <Badge 
                className="text-[10px]"
                style={{ backgroundColor: color, color: '#fff' }}
              >
                {layerNames[step.layer as LayerId]}
              </Badge>
            </div>
            
            {/* 操作描述 */}
            <p className="text-xs text-gray-600 mb-3">
              <span className="text-blue-500 font-medium">▶</span> {descriptions[step.id % descriptions.length] || step.description}
            </p>
            
            {/* 指标网格 */}
            <div className="grid grid-cols-2 gap-2 mb-3">
              <div className="bg-white/60 rounded p-2 text-center">
                <div className="text-lg font-mono font-bold" style={{ color }}>{formatDuration(step.duration, 'full')}</div>
                <div className="text-[10px] text-gray-400">延迟</div>
              </div>
              <div className="bg-white/60 rounded p-2 text-center">
                <div className="text-lg font-mono font-bold text-blue-600">
                  {(step.confidence * 100).toFixed(0)}%
                </div>
                <div className="text-[10px] text-gray-400">置信度</div>
              </div>
              <div className="bg-white/60 rounded p-2 text-center">
                <div className="text-sm font-mono font-bold text-gray-700">
                  {formatTokens(step.inputTokens)}
                </div>
                <div className="text-[10px] text-gray-400">输入</div>
              </div>
              <div className="bg-white/60 rounded p-2 text-center">
                <div className="text-sm font-mono font-bold text-gray-700">
                  {formatTokens(step.outputTokens)}
                </div>
                <div className="text-[10px] text-gray-400">输出</div>
              </div>
            </div>
            
            {/* Token占比条 */}
            <div className="mt-2">
              <div className="flex justify-between text-[10px] text-gray-400 mb-1">
                <span>Token占比</span>
                <span>{step.inputTokens + step.outputTokens}</span>
              </div>
              <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                <div 
                  className="h-full rounded-full"
                  style={{ 
                    width: `${Math.min(100, ((step.inputTokens + step.outputTokens) / 2000) * 100)}%`,
                    backgroundColor: color 
                  }}
                />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}