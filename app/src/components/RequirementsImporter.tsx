import { useState, useCallback, useRef, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { 
  Upload, CheckCircle, FileText, FolderOpen,
  AlertCircle, Clock, Plus, Send, Wand2,
  ListChecks, Code, Bug, Calculator, MessageSquare,
  Lightbulb, Sparkles, Settings,
  File, FileCode, Image, BookOpen,
  Cpu, RefreshCw, Play, Trash2, Radio, Brain
} from 'lucide-react';
import type { TaskType, TaskRequest, TaskResult, ReasoningStep, PerformanceMetrics } from '@/types/morev3';
import { moreEngine } from '@/core/moreEngine';
import { useTaskMemory } from '@/hooks/useTaskMemory';

interface DocumentInput {
  id: string;
  name: string;
  type: 'md' | 'txt' | 'html' | 'pdf' | 'doc' | 'docx';
  size: number;
  content?: string;
  preview?: string;
  pages?: number;
}

interface CustomTask {
  id: string;
  type: TaskType;
  query: string;
  sources?: DocumentInput[];
  status: 'draft' | 'queued' | 'running' | 'completed' | 'failed';
  result?: string;
  progress?: number;
  taskResult?: TaskResult;
  error?: string;
  reasoningChain?: ReasoningStep[];
  performance?: PerformanceMetrics;
}

interface LLMConfig {
  provider: string;
  model: string;
  temperature: number;
  maxTokens: number;
  topP: number;
  frequencyPenalty: number;
  presencePenalty: number;
  enableStream: boolean;
  customEndpoint?: string;
}

const DOCUMENT_TYPES = [
  { ext: 'md', label: 'Markdown', icon: FileCode, color: 'blue' },
  { ext: 'txt', label: '文本', icon: FileText, color: 'gray' },
  { ext: 'html', label: 'HTML', icon: Image, color: 'orange' },
  { ext: 'pdf', label: 'PDF', icon: BookOpen, color: 'red' },
  { ext: 'doc', label: 'Word', icon: File, color: 'blue' },
];

const PROVIDER_PRESETS = [
  { id: 'ollama', name: 'Ollama', models: ['qwen2.5:7b', 'llama3.1:8b', 'codellama:13b', 'mistral:7b'], endpoint: 'http://localhost:11434' },
  { id: 'openai', name: 'OpenAI', models: ['gpt-4o-mini', 'gpt-4o', 'gpt-3.5-turbo'], endpoint: 'https://api.openai.com/v1' },
  { id: 'deepseek', name: 'DeepSeek', models: ['deepseek-chat', 'deepseek-coder'], endpoint: 'https://api.deepseek.com/v1' },
  { id: 'lmstudio', name: 'LM Studio', models: ['gemma-4-coder', 'qwen2.5-coder'], endpoint: 'http://localhost:1234/v1' },
  { id: 'anthropic', name: 'Anthropic', models: ['claude-sonnet-4', 'claude-haiku-3'], endpoint: 'https://api.anthropic.com/v1' },
];

const QUICK_TASKS: { type: TaskType; label: string; icon: React.ReactNode; placeholder: string; suggestedLayers: string[] }[] = [
  { type: 'code_generation', label: '代码生成', icon: <Code className="w-4 h-4" />, placeholder: '描述你想要生成的代码功能...', suggestedLayers: ['L3', 'L4', 'L0'] },
  { type: 'code_debugging', label: '代码调试', icon: <Bug className="w-4 h-4" />, placeholder: '描述遇到的问题和期望的修复...', suggestedLayers: ['L2', 'L4', 'L0'] },
  { type: 'code_review', label: '代码审查', icon: <ListChecks className="w-4 h-4" />, placeholder: '粘贴代码或描述审查重点...', suggestedLayers: ['L3', 'L4', 'L2'] },
  { type: 'architecture_design', label: '架构设计', icon: <Sparkles className="w-4 h-4" />, placeholder: '描述系统需求和约束条件...', suggestedLayers: ['L5', 'L4', 'L3'] },
  { type: 'math_reasoning', label: '数学推理', icon: <Calculator className="w-4 h-4" />, placeholder: '输入数学问题或证明题...', suggestedLayers: ['L4', 'L3', 'L0'] },
  { type: 'data_analysis', label: '数据分析', icon: <Lightbulb className="w-4 h-4" />, placeholder: '描述数据源和分析目标...', suggestedLayers: ['L1', 'L4', 'L0'] },
  { type: 'nlp_task', label: 'NLP任务', icon: <MessageSquare className="w-4 h-4" />, placeholder: '描述NLP任务需求...', suggestedLayers: ['L4', 'L3', 'L0'] },
];

const LAYER_COLORS: Record<string, string> = {
  L0: '#FFD54F', L1: '#FFC107', L2: '#FFB300', L3: '#FFA000', L4: '#FF8F00', L5: '#FF6F00',
};

const MAX_QUERY_LENGTH = 5000;
const QUERY_WARN_THRESHOLD = 4000;

export function RequirementsImporter() {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('input');
  const [customTasks, setCustomTasks] = useState<CustomTask[]>([]);
  const [taskInput, setTaskInput] = useState('');
  const [selectedType, setSelectedType] = useState<TaskType>('code_generation');
  const [documents, setDocuments] = useState<DocumentInput[]>([]);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [showLLMConfig, setShowLLMConfig] = useState(false);
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);
  const [llmConfig, setLlmConfig] = useState<LLMConfig>({
    provider: 'ollama',
    model: 'qwen2.5:7b',
    temperature: 0.7,
    maxTokens: 4096,
    topP: 1,
    frequencyPenalty: 0,
    presencePenalty: 0,
    enableStream: true,
  });

  const fileInputRef = useRef<HTMLInputElement>(null);
  const { stats: memStats, remember, getRelatedContext } = useTaskMemory();

  // Check API connectivity on mount
  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const baseUrl = import.meta.env.VITE_API_BASE || 'http://localhost:8011';
        const res = await fetch(`${baseUrl}/api/v1/health`);
        if (!cancelled) setApiConnected(res.ok);
      } catch {
        if (!cancelled) setApiConnected(false);
      }
    }
    check();
    return () => { cancelled = true; };
  }, []);

  const resetForm = () => {
    setTaskInput('');
    setSelectedType('code_generation');
    setError('');
  };

  const handleFileUpload = useCallback(async (files: FileList | null) => {
    if (!files) return;
    
    const newDocs: DocumentInput[] = [];
    
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const ext = file.name.split('.').pop()?.toLowerCase() || '';
      const docType = DOCUMENT_TYPES.find(d => d.ext === ext)?.ext || 'txt';
      
      let content = '';
      let pages = 1;
      
      if (['md', 'txt', 'html'].includes(ext)) {
        content = await file.text();
      } else if (ext === 'pdf') {
        content = `[PDF文档] ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        pages = Math.ceil(file.size / 50000);
      } else {
        content = `[${ext.toUpperCase()}文档] ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      }
      
      newDocs.push({
        id: `doc_${Date.now()}_${i}`,
        name: file.name,
        type: docType as DocumentInput['type'],
        size: file.size,
        content,
        preview: content.slice(0, 200),
        pages,
      });
    }
    
    setDocuments(prev => [...prev, ...newDocs]);
  }, []);

  const removeDocument = (id: string) => {
    setDocuments(prev => prev.filter(d => d.id !== id));
  };

  const handleQuickTaskSubmit = useCallback(async (task: typeof QUICK_TASKS[0]) => {
    if (!taskInput.trim() && documents.length === 0) {
      setError('请输入任务描述或上传文档');
      return;
    }

    // Query length validation
    const trimmed = taskInput.trim();
    if (trimmed.length > MAX_QUERY_LENGTH) {
      setError(`任务描述过长 (${trimmed.length}/${MAX_QUERY_LENGTH} 字符)，请精简后再提交`);
      return;
    }

    setSubmitting(true);
    setError('');

    const sources = documents.length > 0 ? [...documents] : undefined;
    const query = trimmed || '基于上传文档处理';
    const taskId = `task_${Date.now()}`;
    
    const newTask: CustomTask = {
      id: taskId,
      type: task.type,
      query,
      sources,
      status: 'running',
    };

    setCustomTasks(prev => [newTask, ...prev]);

    // Build a real TaskRequest and call the backend via moreEngine
    // Inject related past task context for memory-augmented execution
    const memoryContext = getRelatedContext(query, task.type);
    const contextPayload: Record<string, any> = {
      source: 'requirements_importer',
      document_count: documents.length,
      documents: documents.map(d => ({ name: d.name, type: d.type })),
    };
    if (memoryContext) {
      contextPayload.memory_context = memoryContext;
    }

    const request: TaskRequest = {
      id: taskId,
      type: task.type,
      query,
      context: contextPayload,
      requireMetacognitiveMonitoring: false,
    };

    try {
      const result: TaskResult = await moreEngine.executeTask(request);

      // Record to memory bank for future context
      // Only record real API results to memory (not simulated fallbacks)
      if (result.output && result.output.length > 100) {
        remember(result, query);
      }

      setCustomTasks(prev => prev.map(t => 
        t.id === taskId ? {
          ...t,
          status: result.status === 'success' ? 'completed' : (result.status === 'failed' ? 'failed' : 'completed'),
          progress: 100,
          result: result.output,
          taskResult: result,
          reasoningChain: result.reasoningChain,
          performance: result.performance,
        } : t
      ));
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setCustomTasks(prev => prev.map(t => 
        t.id === taskId ? {
          ...t,
          status: 'failed',
          progress: 100,
          error: msg,
          result: `API 调用失败: ${msg}`,
        } : t
      ));
    } finally {
      setSubmitting(false);
    }

    resetForm();
    setDocuments([]);
  }, [taskInput, documents]);

  const handleBatchTasks = useCallback(async (requests: string[]) => {
    const now = Date.now();
    const newTasks: CustomTask[] = requests.map((q, i) => ({
      id: `batch_${now}_${i}`,
      type: selectedType,
      query: q,
      status: 'running' as const,
    }));
    setCustomTasks(prev => [...newTasks, ...prev]);
    
    // Execute all tasks concurrently via real API
    await Promise.all(newTasks.map(async (task) => {
      const request: TaskRequest = {
        id: task.id,
        type: task.type,
        query: task.query,
        context: { source: 'requirements_importer_batch' },
        requireMetacognitiveMonitoring: false,
      };
      try {
        const result: TaskResult = await moreEngine.executeTask(request);
        setCustomTasks(prev => prev.map(t => 
          t.id === task.id ? {
            ...t,
            status: result.status === 'success' ? 'completed' : 'failed',
            result: result.output,
            taskResult: result,
            reasoningChain: result.reasoningChain,
            performance: result.performance,
          } : t
        ));
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setCustomTasks(prev => prev.map(t => 
          t.id === task.id ? { ...t, status: 'failed', error: msg, result: msg } : t
        ));
      }
    }));
  }, [selectedType]);

  const getStatusConfig = (status: CustomTask['status']) => {
    switch (status) {
      case 'completed':
        return { icon: <CheckCircle className="w-4 h-4 text-green-500" />, text: '已完成', bg: 'bg-green-50', textColor: 'text-green-700' };
      case 'failed':
        return { icon: <AlertCircle className="w-4 h-4 text-red-500" />, text: '失败', bg: 'bg-red-50', textColor: 'text-red-700' };
      case 'running':
        return { icon: <RefreshCw className="w-4 h-4 text-orange-500 animate-spin" />, text: '执行中', bg: 'bg-orange-50', textColor: 'text-orange-700' };
      case 'queued':
        return { icon: <Clock className="w-4 h-4 text-gray-400" />, text: '排队中', bg: 'bg-gray-50', textColor: 'text-gray-500' };
      default:
        return { icon: <Clock className="w-4 h-4 text-gray-400" />, text: '草稿', bg: 'bg-gray-50', textColor: 'text-gray-500' };
    }
  };

  const getDocIcon = (type: string) => {
    const docConfig = DOCUMENT_TYPES.find(d => d.ext === type);
    const Icon = docConfig?.icon || FileText;
    return <Icon className="w-4 h-4" />;
  };

  const updateLlmConfig = (key: keyof LLMConfig, value: unknown) => {
    setLlmConfig(prev => ({ ...prev, [key]: value }));
  };

  const currentProvider = PROVIDER_PRESETS.find(p => p.id === llmConfig.provider);

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <Wand2 className="w-4 h-4" />
          任务导入
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-6xl max-h-[95vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Wand2 className="w-5 h-5 text-orange-500" />
              MoRE 任务输入端口
              {memStats.totalMemories > 0 && (
                <Badge variant="outline" className="text-[10px] bg-purple-50 text-purple-600 border-purple-200 gap-1">
                  <Brain className="w-3 h-3" /> {memStats.totalMemories} 记忆
                </Badge>
              )}
              {apiConnected === null ? (
                <Badge variant="outline" className="text-[10px] bg-gray-100 text-gray-500">
                  <div className="w-2 h-2 rounded-full bg-gray-400 animate-pulse mr-1" /> 检测中
                </Badge>
              ) : apiConnected ? (
                <Badge variant="outline" className="text-[10px] bg-green-50 text-green-700 border-green-200">
                  <Radio className="w-3 h-3 mr-1 text-green-500" /> API 已连接
                </Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] bg-red-50 text-red-700 border-red-200">
                  <AlertCircle className="w-3 h-3 mr-1 text-red-500" /> API 离线
                </Badge>
              )}
            </div>
            <Button variant="ghost" size="sm" onClick={() => setShowLLMConfig(!showLLMConfig)}>
              <Settings className="w-4 h-4" />
              {showLLMConfig ? '隐藏' : ''} LLM配置
            </Button>
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-hidden flex flex-col">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col overflow-hidden">
            <TabsList className="grid w-full grid-cols-4 mb-4">
              <TabsTrigger value="input" className="text-xs gap-1">
                <FileText className="w-3 h-3" /> 文档输入
              </TabsTrigger>
              <TabsTrigger value="quick" className="text-xs gap-1">
                <Plus className="w-3 h-3" /> 快速输入
              </TabsTrigger>
              <TabsTrigger value="batch" className="text-xs gap-1">
                <ListChecks className="w-3 h-3" /> 批量导入
              </TabsTrigger>
              <TabsTrigger value="history" className="text-xs gap-1">
                <Clock className="w-3 h-3" /> 执行历史
              </TabsTrigger>
            </TabsList>

            {showLLMConfig && (
              <Card className="mb-4">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-purple-500" />
                    LLM 模型配置
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-4 gap-4">
                    <div className="space-y-2">
                      <Label className="text-xs">Provider</Label>
                      <select
                        value={llmConfig.provider}
                        onChange={(e) => {
                          const provider = PROVIDER_PRESETS.find(p => p.id === e.target.value);
                          updateLlmConfig('provider', e.target.value);
                          if (provider) updateLlmConfig('model', provider.models[0]);
                        }}
                        className="w-full text-xs border rounded px-2 py-1.5"
                      >
                        {PROVIDER_PRESETS.map(p => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Model</Label>
                      <select
                        value={llmConfig.model}
                        onChange={(e) => updateLlmConfig('model', e.target.value)}
                        className="w-full text-xs border rounded px-2 py-1.5"
                      >
                        {currentProvider?.models.map(m => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Temperature ({llmConfig.temperature})</Label>
                      <Slider
                        value={[llmConfig.temperature]}
                        min={0}
                        max={2}
                        step={0.1}
                        onValueChange={(v) => updateLlmConfig('temperature', v[0])}
                        className="mt-2"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Max Tokens ({llmConfig.maxTokens})</Label>
                      <Slider
                        value={[llmConfig.maxTokens]}
                        min={256}
                        max={8192}
                        step={256}
                        onValueChange={(v) => updateLlmConfig('maxTokens', v[0])}
                        className="mt-2"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-4 gap-4 mt-4">
                    <div className="space-y-2">
                      <Label className="text-xs">Top P ({llmConfig.topP})</Label>
                      <Slider
                        value={[llmConfig.topP]}
                        min={0}
                        max={1}
                        step={0.1}
                        onValueChange={(v) => updateLlmConfig('topP', v[0])}
                        className="mt-2"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Frequency Penalty ({llmConfig.frequencyPenalty})</Label>
                      <Slider
                        value={[llmConfig.frequencyPenalty]}
                        min={-2}
                        max={2}
                        step={0.1}
                        onValueChange={(v) => updateLlmConfig('frequencyPenalty', v[0])}
                        className="mt-2"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Presence Penalty ({llmConfig.presencePenalty})</Label>
                      <Slider
                        value={[llmConfig.presencePenalty]}
                        min={-2}
                        max={2}
                        step={0.1}
                        onValueChange={(v) => updateLlmConfig('presencePenalty', v[0])}
                        className="mt-2"
                      />
                    </div>
                    <div className="space-y-2 flex items-center justify-between">
                      <Label className="text-xs">Enable Stream</Label>
                      <Switch
                        checked={llmConfig.enableStream}
                        onCheckedChange={(v) => updateLlmConfig('enableStream', v)}
                      />
                    </div>
                  </div>
                  <div className="mt-4 flex items-center gap-2">
                    <Input
                      placeholder="Custom endpoint (可选)"
                      value={llmConfig.customEndpoint || ''}
                      onChange={(e) => updateLlmConfig('customEndpoint', e.target.value)}
                      className="flex-1 text-xs"
                    />
                    <Button size="sm" variant="outline">保存配置</Button>
                    <Button size="sm" variant="ghost">重置</Button>
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="flex-1 overflow-hidden flex flex-col">
              <TabsContent value="input" className="flex-1 flex flex-col overflow-hidden space-y-4">
                <Card className="flex-1 flex flex-col overflow-hidden">
                  <CardHeader className="pb-2 flex-shrink-0">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <FolderOpen className="w-4 h-4 text-blue-500" />
                      多模态文档输入
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="flex-1 overflow-hidden flex flex-col">
                    <div className="flex items-center gap-2 mb-3 flex-wrap">
                      <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        accept=".md,.txt,.html,.pdf,.doc,.docx"
                        onChange={(e) => handleFileUpload(e.target.files)}
                        className="hidden"
                      />
                      <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                        <Upload className="w-3 h-3 mr-1" /> 上传文件
                      </Button>
                      {DOCUMENT_TYPES.map(doc => {
                        const Icon = doc.icon;
                        return (
                          <Badge key={doc.ext} variant="outline" className="text-[10px] gap-1">
                            <Icon className="w-3 h-3" />
                            {doc.label}
                          </Badge>
                        );
                      })}
                    </div>

                    {documents.length > 0 && (
                      <div className="mb-3 space-y-2 max-h-[150px] overflow-y-auto">
                        {documents.map(doc => (
                          <div key={doc.id} className="flex items-center gap-2 p-2 bg-gray-50 rounded">
                            {getDocIcon(doc.type)}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-medium truncate">{doc.name}</span>
                                <Badge variant="outline" className="text-[8px]">{doc.type.toUpperCase()}</Badge>
                                {doc.pages && <Badge variant="outline" className="text-[8px]">{doc.pages}页</Badge>}
                              </div>
                              <span className="text-[10px] text-gray-400">
                                {(doc.size / 1024).toFixed(1)} KB
                              </span>
                            </div>
                            <Button variant="ghost" size="sm" onClick={() => removeDocument(doc.id)}>
                              <Trash2 className="w-3 h-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="flex-1 overflow-hidden flex flex-col space-y-3">
                      <div className="flex items-center justify-between flex-shrink-0">
                        <span className="text-xs text-gray-500">任务描述</span>
                        <div className="flex items-center gap-1">
                          {QUICK_TASKS.find(t => t.type === selectedType)?.suggestedLayers.map(layer => (
                            <Badge
                              key={layer}
                              className="text-[8px] h-4 px-1 font-mono"
                              style={{ backgroundColor: LAYER_COLORS[layer], color: '#fff' }}
                            >
                              {layer}
                            </Badge>
                          ))}
                        </div>
                      </div>
                      <Textarea
                        value={taskInput}
                        onChange={(e) => setTaskInput(e.target.value)}
                        placeholder="描述任务需求，或直接上传文档后输入..."
                        className="flex-1 text-sm min-h-[120px]"
                        maxLength={MAX_QUERY_LENGTH + 500}
                      />
                      <div className={`text-[10px] text-right ${taskInput.length > MAX_QUERY_LENGTH ? 'text-red-500 font-bold' : taskInput.length > QUERY_WARN_THRESHOLD ? 'text-orange-500' : 'text-gray-400'}`}>
                        {taskInput.length} / {MAX_QUERY_LENGTH}
                      </div>
                    </div>

                    <div className="flex items-center gap-4 mt-3 flex-shrink-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">任务类型</span>
                        <select
                          value={selectedType}
                          onChange={(e) => setSelectedType(e.target.value as TaskType)}
                          className="text-xs border rounded px-2 py-1"
                        >
                          {QUICK_TASKS.map(task => (
                            <option key={task.type} value={task.type}>{task.label}</option>
                          ))}
                        </select>
                      </div>
                      <div className="flex-1" />
                      {error && (
                        <div className="flex items-center gap-2 text-red-500 text-xs">
                          <AlertCircle className="w-3 h-3" />
                          {error}
                        </div>
                      )}
                      <Button
                        onClick={() => handleQuickTaskSubmit(QUICK_TASKS.find(t => t.type === selectedType)!)}
                        disabled={submitting || (!taskInput.trim() && documents.length === 0)}
                        className="gap-2 bg-orange-500 hover:bg-orange-600"
                      >
                        {submitting ? (
                          <><RefreshCw className="w-4 h-4 animate-spin" /> 处理中...</>
                        ) : (
                          <><Play className="w-4 h-4" /> 开始处理</>
                        )}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="quick" className="flex-1 overflow-y-auto space-y-4">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Send className="w-4 h-4 text-orange-500" />
                      快速任务输入
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid grid-cols-4 gap-2">
                      {QUICK_TASKS.map(task => (
                        <Button
                          key={task.type}
                          variant={selectedType === task.type ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => setSelectedType(task.type)}
                          className={`h-auto py-2 px-2 flex-col gap-1 ${
                            selectedType === task.type ? 'bg-orange-500' : ''
                          }`}
                        >
                          {task.icon}
                          <span className="text-[10px]">{task.label}</span>
                        </Button>
                      ))}
                    </div>

                    <Textarea
                      value={taskInput}
                      onChange={(e) => setTaskInput(e.target.value)}
                      placeholder={QUICK_TASKS.find(t => t.type === selectedType)?.placeholder}
                      className="min-h-[120px] text-sm"
                      maxLength={MAX_QUERY_LENGTH + 500}
                    />
                    <div className={`text-[10px] text-right ${taskInput.length > MAX_QUERY_LENGTH ? 'text-red-500 font-bold' : taskInput.length > QUERY_WARN_THRESHOLD ? 'text-orange-500' : 'text-gray-400'}`}>
                      {taskInput.length} / {MAX_QUERY_LENGTH}
                    </div>

                    {error && (
                      <div className="flex items-center gap-2 text-red-500 text-sm p-2 bg-red-50 rounded">
                        <AlertCircle className="w-4 h-4" />
                        {error}
                      </div>
                    )}

                    <Button
                      onClick={() => handleQuickTaskSubmit(QUICK_TASKS.find(t => t.type === selectedType)!)}
                      disabled={submitting || !taskInput.trim()}
                      className="w-full gap-2 bg-orange-500 hover:bg-orange-600"
                    >
                      <Send className="w-4 h-4" />
                      提交任务
                    </Button>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="batch" className="flex-1 overflow-y-auto space-y-4">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <ListChecks className="w-4 h-4 text-blue-500" />
                      批量任务导入
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">任务类型</span>
                        <select
                          value={selectedType}
                          onChange={(e) => setSelectedType(e.target.value as TaskType)}
                          className="text-xs border rounded px-2 py-1"
                        >
                          {QUICK_TASKS.map(task => (
                            <option key={task.type} value={task.type}>{task.label}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <Textarea
                      placeholder="任务1: 实现用户登录功能&#10;任务2: 添加密码重置&#10;任务3: 实现OAuth登录&#10;..."
                      className="min-h-[200px] text-sm font-mono"
                      onChange={(e) => setTaskInput(e.target.value)}
                      value={taskInput}
                    />

                    <Button
                      onClick={() => {
                        const lines = taskInput.split('\n').filter(l => l.trim());
                        if (lines.length === 0) {
                          setError('请输入至少一个任务');
                          return;
                        }
                        // Validate each line length
                        const tooLong = lines.filter(l => l.length > MAX_QUERY_LENGTH);
                        if (tooLong.length > 0) {
                          setError(`${tooLong.length} 个任务描述超长 (>${MAX_QUERY_LENGTH} 字符)，请精简后再提交`);
                          return;
                        }
                        handleBatchTasks(lines);
                        setTaskInput('');
                      }}
                      className="w-full gap-2 bg-blue-600 hover:bg-blue-700"
                    >
                      <Upload className="w-4 h-4" />
                      批量导入 ({taskInput.split('\n').filter(l => l.trim()).length} 任务)
                    </Button>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="history" className="flex-1 overflow-y-auto">
                <Card className="h-full">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Clock className="w-4 h-4 text-gray-500" />
                      执行历史
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {customTasks.length > 0 ? (
                      <ScrollArea className="h-[calc(100vh-400px)]">
                        <div className="space-y-3">
                          {customTasks.map(task => {
                            const config = getStatusConfig(task.status);
                            return (
                              <div key={task.id} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                                {config.icon}
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                                    <Badge variant="outline" className="text-[8px]">{task.type}</Badge>
                                    <span className={`text-xs px-2 py-0.5 rounded ${config.bg} ${config.textColor}`}>
                                      {config.text}
                                    </span>
                                    <span className="text-[10px] text-gray-400">
                                      {new Date(parseInt(task.id.split('_')[1])).toLocaleString()}
                                    </span>
                                  </div>
                                  <p className="text-sm text-gray-700">{task.query}</p>
                                  {task.progress !== undefined && task.progress < 100 && (
                                    <div className="mt-2">
                                      <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
                                        <div 
                                          className="h-full bg-orange-500 rounded-full transition-all"
                                          style={{ width: `${task.progress}%` }}
                                        />
                                      </div>
                                    </div>
                                  )}
                                  {task.result && (
                                    <p className="text-xs text-gray-500 mt-1 bg-white p-2 rounded max-h-24 overflow-y-auto">{task.result}</p>
                                  )}
                                  {task.reasoningChain && task.reasoningChain.length > 0 && (
                                    <div className="mt-1 flex items-center gap-1 flex-wrap">
                                      {task.reasoningChain.map((step, i) => (
                                        <span key={i} className="text-[9px] bg-orange-100 text-orange-700 px-1 rounded font-mono">
                                          {step.layer}
                                        </span>
                                      ))}
                                      {task.performance && (
                                        <span className="text-[9px] text-gray-400">
                                          {task.performance.totalDuration?.toFixed(0)}ms
                                        </span>
                                      )}
                                    </div>
                                  )}
                                  {task.error && (
                                    <p className="text-xs text-red-500 mt-1 bg-red-50 p-1 rounded">{task.error}</p>
                                  )}
                                  {task.sources && task.sources.length > 0 && (
                                    <div className="flex items-center gap-1 mt-1">
                                      <File className="w-3 h-3 text-gray-400" />
                                      <span className="text-[10px] text-gray-400">{task.sources.length} 个文档</span>
                                    </div>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </ScrollArea>
                    ) : (
                      <div className="text-center py-12 text-gray-400">
                        <Clock className="w-12 h-12 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">暂无执行历史</p>
                        <p className="text-xs">提交任务后将通过 MoRE OS API 执行并自动记录</p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>
            </div>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  );
}