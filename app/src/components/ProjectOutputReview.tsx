import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from 'sonner';
import { 
  FolderOpen, FileText, CheckCircle,
  Star, ChevronRight, File, Code, RotateCw, MessageSquare, Trash2
} from 'lucide-react';

interface ProjectOutputFile {
  path: string;
  type: string;
  lines: number;
  preview?: string;
}

interface ProjectOutput {
  id: string;
  name: string;
  type: string;
  status: string;
  created_at: string;
  files: ProjectOutputFile[];
  tests: { path: string; type: string; status: string }[];
  docs: { path: string; type: string }[];
  review?: {
    rating: number;
    comments: string;
    approved: boolean;
    feedback: string;
    reviewed_at: string;
  } | null;
  iteration_count: number;
  metadata?: {
    task_id?: string;
    original_status?: string;
    performance?: { total_duration?: number; tokens_used?: number };
    layers?: string[];
    output_preview?: string;
    output_full?: string;
    review_summary?: string;
    iteration_of?: string;
  };
}

interface ReviewData {
  rating: number;
  comments: string;
  approved: boolean;
  feedback: string;
}

interface IterationData {
  feedback: string;
  target_improvements: string[];
}

export function ProjectOutputReview() {
  const [outputs, setOutputs] = useState<ProjectOutput[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedOutput, setSelectedOutput] = useState<ProjectOutput | null>(null);
  const [reviewData, setReviewData] = useState<ReviewData>({ rating: 0, comments: '', approved: false, feedback: '' });
  const [iterationData, setIterationData] = useState<IterationData>({ feedback: '', target_improvements: [] });
  const [error, setError] = useState('');
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [activeView, setActiveView] = useState<'all' | 'code' | 'docs'>('all');
  const [modalMode, setModalMode] = useState<'view' | 'review' | 'iterate'>('view');
  const [iterating, setIterating] = useState(false);

  const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8010';

  useEffect(() => {
    // Check API health first
    fetch(`${API_BASE}/api/v1/health`)
      .then(r => { setApiOnline(r.ok); fetchOutputs(); })
      .catch(() => { setApiOnline(false); setError('无法连接到服务器 (http://localhost:8010)'); setLoading(false); });
  }, []);

  const fetchOutputs = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/projects/outputs`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setOutputs(data.outputs || []);
    } catch (e: any) {
      if (e.message.includes('Failed to fetch') || e.message.includes('NetworkError')) {
        setError('无法连接到服务器，请确保后端服务正在运行');
      } else {
        setError('获取项目产出物失败: ' + e.message);
      }
    } finally {
      setLoading(false);
    }
  };

  const filteredOutputs = outputs.filter(output => {
    if (activeView === 'all') return true;
    if (activeView === 'code') return output.type.includes('code');
    if (activeView === 'docs') return output.docs.length > 0;
    return true;
  });

  const stats = {
    total: outputs.length,
    code: outputs.filter(o => o.files.length > 0).length,
    docs: outputs.filter(o => o.docs.length > 0).length,
    files: outputs.reduce((sum, o) => sum + o.files.length, 0),
    iterated: outputs.filter(o => o.iteration_count > 0).length,
  };

  const submitReview = async () => {
    if (!selectedOutput) return;
    try {
      const response = await fetch(`${API_BASE}/api/v1/projects/outputs/${selectedOutput.id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reviewData),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      toast.success(`评审提交成功！批准状态: ${data.output.review.approved ? '已批准' : '未批准'}，评分: ${data.output.review.rating}星`);
      setSelectedOutput(null);
      setReviewData({ rating: 0, comments: '', approved: false, feedback: '' });
      fetchOutputs();
    } catch (e: any) {
      toast.error(`评审提交失败: ${e.message}`);
    }
  };

  const submitIteration = async () => {
    if (!selectedOutput || !iterationData.feedback) return;
    setIterating(true);
    try {
      const response = await fetch(`${API_BASE}/api/v1/projects/outputs/${selectedOutput.id}/iterate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(iterationData),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (data.new_output) {
        toast.success(`迭代完成！新产出物: ${data.new_output.name}`);
      } else {
        toast.warning('迭代完成，但新产出物生成失败（可能缺少 LLM Provider 配置）');
      }
      setSelectedOutput(null);
      setIterationData({ feedback: '', target_improvements: [] });
      fetchOutputs();
    } catch (e: any) {
      toast.error(`迭代失败: ${e.message}`);
    } finally {
      setIterating(false);
    }
  };

  const deleteOutput = async (outputId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('确定要删除此产出物吗？')) return;
    try {
      const response = await fetch(`${API_BASE}/api/v1/projects/outputs/${outputId}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      toast.success('产出物已删除');
      if (selectedOutput?.id === outputId) {
        setSelectedOutput(null);
      }
      fetchOutputs();
    } catch (e: any) {
      toast.error(`删除失败: ${e.message}`);
    }
  };

  const openForReview = (output: ProjectOutput) => {
    setSelectedOutput(output);
    setModalMode('review');
    setReviewData({ rating: 0, comments: '', approved: false, feedback: '' });
  };

  const openForIteration = (output: ProjectOutput) => {
    setSelectedOutput(output);
    setModalMode('iterate');
    setIterationData({ feedback: '', target_improvements: [] });
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-green-500';
      case 'approved': return 'bg-emerald-500';
      case 'pending_review': return 'bg-yellow-500';
      case 'needs_iteration': return 'bg-orange-500';
      case 'iterated': return 'bg-blue-500';
      case 'in_progress': return 'bg-blue-400';
      default: return 'bg-gray-500';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'completed': return '已完成';
      case 'approved': return '已批准';
      case 'pending_review': return '待评审';
      case 'needs_iteration': return '需迭代';
      case 'iterated': return '已迭代';
      case 'in_progress': return '进行中';
      default: return status;
    }
  };

  const getTypeColor = (type: string) => {
    if (type.includes('code_generation') || type.includes('code')) return 'text-blue-600';
    if (type.includes('nlp')) return 'text-purple-600';
    if (type.includes('math')) return 'text-green-600';
    return 'text-gray-600';
  };

  const getFileIcon = (type: string) => {
    if (type === 'python' || type === 'typescript' || type === 'javascript') return <Code className="w-4 h-4 text-blue-500" />;
    if (type === 'markdown' || type === 'docs') return <FileText className="w-4 h-4 text-green-500" />;
    return <File className="w-4 h-4 text-gray-500" />;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <FolderOpen className="w-5 h-5" />
          项目产出物
        </h2>
        <div className="flex items-center gap-2">
          {apiOnline === true && (
            <Badge variant="outline" className="text-xs bg-green-50 text-green-700 border-green-200 gap-1">
              <div className="w-2 h-2 rounded-full bg-green-500" /> 已连接
            </Badge>
          )}
          <Button onClick={fetchOutputs} variant="outline" size="sm">
            刷新
          </Button>
        </div>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-5 gap-3">
        <Card className="bg-gradient-to-br from-blue-50 to-blue-100 border-blue-200">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-blue-600">{stats.total}</div>
            <div className="text-xs text-blue-500">总产出物</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-green-50 to-green-100 border-green-200">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-green-600">{stats.code}</div>
            <div className="text-xs text-green-500">代码产出</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-purple-50 to-purple-100 border-purple-200">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-purple-600">{stats.docs}</div>
            <div className="text-xs text-purple-500">文档产出</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-orange-50 to-orange-100 border-orange-200">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-orange-600">{stats.files}</div>
            <div className="text-xs text-orange-500">文件总数</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-cyan-50 to-cyan-100 border-cyan-200">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-cyan-600">{stats.iterated}</div>
            <div className="text-xs text-cyan-500">迭代次数</div>
          </CardContent>
        </Card>
      </div>

      {/* 过滤标签 */}
      <Tabs value={activeView} onValueChange={(v: string) => setActiveView(v as any)}>
        <TabsList className="w-full grid grid-cols-3">
          <TabsTrigger value="all" className="text-xs">
            <FolderOpen className="w-3 h-3 mr-1" />
            全部 ({stats.total})
          </TabsTrigger>
          <TabsTrigger value="code" className="text-xs">
            <Code className="w-3 h-3 mr-1" />
            代码 ({stats.code})
          </TabsTrigger>
          <TabsTrigger value="docs" className="text-xs">
            <FileText className="w-3 h-3 mr-1" />
            文档 ({stats.docs})
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center justify-between mb-1">
            <span className="text-red-700 text-sm font-medium">{error}</span>
            <Button variant="ghost" size="sm" className="text-xs h-6 text-red-600" onClick={fetchOutputs}>
              重试
            </Button>
          </div>
          {apiOnline === false && (
            <p className="text-xs text-red-500">API 服务未响应，请确认 http://localhost:8010 已启动</p>
          )}
        </div>
      )}

      {loading ? (
        <div className="text-center py-8">
          <div className="w-8 h-8 border-2 border-orange-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <div className="text-sm text-gray-500 mt-2">加载中...</div>
        </div>
      ) : filteredOutputs.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          <FolderOpen className="w-12 h-12 mx-auto mb-2 text-gray-300" />
          <p>暂无{activeView === 'code' ? '代码' : activeView === 'docs' ? '文档' : ''}产出物</p>
          <p className="text-xs text-gray-400 mt-1">执行任务后将自动生成产出物</p>
        </div>
      ) : (
        <ScrollArea className="h-[500px]">
          <div className="grid grid-cols-2 gap-4">
            {filteredOutputs.map((output) => (
              <Card key={output.id} className="hover:shadow-md transition-shadow cursor-pointer border-gray-200 hover:border-orange-300"
                    onClick={() => { setSelectedOutput(output); setModalMode('view'); }}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm truncate flex-1">{output.name}</CardTitle>
                    <div className="flex items-center gap-1">
                      {output.iteration_count > 0 && (
                        <Badge variant="outline" className="text-[10px] bg-cyan-50 text-cyan-600 border-cyan-200">
                          <RotateCw className="w-2.5 h-2.5 mr-0.5" />
                          {output.iteration_count}
                        </Badge>
                      )}
                      <Badge className={getStatusColor(output.status)}>
                        {getStatusText(output.status)}
                      </Badge>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500 mt-1">
                    <span className={`font-medium ${getTypeColor(output.type)}`}>
                      {output.type.replace(/_/g, ' ')}
                    </span>
                    <span>|</span>
                    <span>{new Date(output.created_at).toLocaleString('zh-CN')}</span>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div className="flex items-center gap-1 bg-blue-50 rounded px-2 py-1">
                      <Code className="w-3 h-3 text-blue-500" />
                      <span>{output.files.length} 文件</span>
                    </div>
                    <div className="flex items-center gap-1 bg-green-50 rounded px-2 py-1">
                      <CheckCircle className="w-3 h-3 text-green-500" />
                      <span>{output.tests.length} 测试</span>
                    </div>
                    <div className="flex items-center gap-1 bg-purple-50 rounded px-2 py-1">
                      <FileText className="w-3 h-3 text-purple-500" />
                      <span>{output.docs.length} 文档</span>
                    </div>
                  </div>
                  {output.metadata?.layers && output.metadata.layers.length > 0 && (
                    <div className="flex gap-1 mt-2 flex-wrap">
                      {output.metadata.layers.slice(0, 3).map((layer, idx) => (
                        <span key={idx} className="text-[10px] bg-orange-100 text-orange-600 px-1.5 py-0.5 rounded">
                          {layer}
                        </span>
                      ))}
                    </div>
                  )}
                  {output.files.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {output.files.slice(0, 3).map((file, idx) => (
                        <span key={idx} className="text-[10px] bg-gray-100 px-2 py-1 rounded flex items-center gap-1">
                          {getFileIcon(file.type)}
                          <span className="truncate max-w-[100px]">{file.path.split('/').pop()}</span>
                        </span>
                      ))}
                      {output.files.length > 3 && (
                        <span className="text-xs text-gray-500">+{output.files.length - 3}</span>
                      )}
                    </div>
                  )}
                  {output.review && (
                    <div className="mt-2 flex items-center gap-1 text-xs">
                      <Star className="w-3 h-3 text-yellow-500 fill-yellow-500" />
                      <span className="text-yellow-600">{output.review.rating}/5</span>
                      {output.review.approved && <CheckCircle className="w-3 h-3 text-green-500 ml-1" />}
                    </div>
                  )}
                  <div className="mt-2 flex items-center justify-between">
                    <span className="text-[10px] text-gray-400">
                      {output.metadata?.performance?.tokens_used || 0} tokens
                    </span>
                    <div className="flex items-center gap-1">
                      <button 
                        onClick={(e) => { e.stopPropagation(); openForReview(output); }}
                        className="p-1 hover:bg-gray-100 rounded"
                        title="评审"
                      >
                        <Star className="w-3.5 h-3.5 text-gray-400" />
                      </button>
                      <button 
                        onClick={(e) => { e.stopPropagation(); openForIteration(output); }}
                        className="p-1 hover:bg-gray-100 rounded"
                        title="迭代"
                      >
                        <RotateCw className="w-3.5 h-3.5 text-gray-400" />
                      </button>
                      <button 
                        onClick={(e) => deleteOutput(output.id, e)}
                        className="p-1 hover:bg-gray-100 rounded"
                        title="删除"
                      >
                        <Trash2 className="w-3.5 h-3.5 text-gray-400" />
                      </button>
                      <ChevronRight className="w-4 h-4 text-gray-400" />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </ScrollArea>
      )}

      {/* 评审弹窗 */}
      {selectedOutput && modalMode === 'review' && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-[600px] max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Star className="w-5 h-5 text-yellow-500" />
                评审: {selectedOutput.name}
              </h3>
              <button onClick={() => setSelectedOutput(null)} className="text-gray-500 hover:text-gray-700">✕</button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">产出物详情</label>
                <div className="bg-gray-50 rounded-lg p-3 text-sm">
                  <div className="grid grid-cols-2 gap-2 mb-3">
                    <div>类型: <span className={getTypeColor(selectedOutput.type)}>{selectedOutput.type}</span></div>
                    <div>状态: {getStatusText(selectedOutput.status)}</div>
                    <div>文件: {selectedOutput.files.length}</div>
                    <div>迭代: {selectedOutput.iteration_count}</div>
                  </div>
                  {selectedOutput.files.length > 0 && (
                    <>
                      <div className="mb-2 font-medium">文件列表:</div>
                      {selectedOutput.files.map((file, idx) => (
                        <div key={idx} className="flex items-center gap-2 text-xs ml-2 py-1">
                          {getFileIcon(file.type)}
                          <span className="flex-1 truncate">{file.path}</span>
                          <span className="text-gray-500">{file.lines} 行</span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">评分 (0-5星)</label>
                <div className="flex gap-1">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button key={star} onClick={() => setReviewData({ ...reviewData, rating: star })}
                            className="p-1 hover:scale-110 transition-transform">
                      <Star className={`w-6 h-6 ${star <= reviewData.rating ? 'text-yellow-500 fill-yellow-500' : 'text-gray-300'}`} />
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">评审意见</label>
                <textarea 
                  value={reviewData.comments}
                  onChange={(e) => setReviewData({ ...reviewData, comments: e.target.value })}
                  placeholder="请输入评审意见..."
                  className="w-full h-24 p-3 border rounded-lg text-sm resize-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">改进建议（用于迭代）</label>
                <textarea 
                  value={reviewData.feedback}
                  onChange={(e) => setReviewData({ ...reviewData, feedback: e.target.value })}
                  placeholder="如需迭代，请输入改进建议..."
                  className="w-full h-20 p-3 border rounded-lg text-sm resize-none"
                />
              </div>

              <div className="flex items-center gap-2">
                <input 
                  type="checkbox" 
                  id="approved"
                  checked={reviewData.approved}
                  onChange={(e) => setReviewData({ ...reviewData, approved: e.target.checked })}
                  className="w-4 h-4"
                />
                <label htmlFor="approved" className="text-sm">批准此产出物</label>
              </div>

              <div className="flex gap-2 justify-end pt-4">
                <Button variant="outline" onClick={() => setSelectedOutput(null)}>取消</Button>
                <Button onClick={submitReview} className="bg-orange-500 hover:bg-orange-600">提交评审</Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 迭代弹窗 */}
      {selectedOutput && modalMode === 'iterate' && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-[600px] max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <RotateCw className="w-5 h-5 text-cyan-500" />
                迭代: {selectedOutput.name}
              </h3>
              <button onClick={() => setSelectedOutput(null)} className="text-gray-500 hover:text-gray-700">✕</button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">当前版本信息</label>
                <div className="bg-gray-50 rounded-lg p-3 text-sm">
                  <div className="grid grid-cols-2 gap-2">
                    <div>版本: v{selectedOutput.iteration_count + 1}</div>
                    <div>文件: {selectedOutput.files.length}</div>
                    {selectedOutput.review && (
                      <>
                        <div>评分: {selectedOutput.review.rating}/5</div>
                        <div>状态: {selectedOutput.review.approved ? '已批准' : '未批准'}</div>
                      </>
                    )}
                  </div>
                  {selectedOutput.review?.comments && (
                    <div className="mt-2 text-xs text-gray-600">
                      评审意见: {selectedOutput.review.comments}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">反馈内容 *</label>
                <textarea 
                  value={iterationData.feedback}
                  onChange={(e) => setIterationData({ ...iterationData, feedback: e.target.value })}
                  placeholder="请描述需要改进的内容..."
                  className="w-full h-32 p-3 border rounded-lg text-sm resize-none"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">目标改进（可选，回车添加）</label>
                <div className="flex gap-2 mb-2">
                  <input 
                    type="text"
                    placeholder="输入改进目标后回车..."
                    className="flex-1 p-2 border rounded-lg text-sm"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                        e.preventDefault();
                        setIterationData({
                          ...iterationData,
                          target_improvements: [...iterationData.target_improvements, e.currentTarget.value.trim()]
                        });
                        e.currentTarget.value = '';
                      }
                    }}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  {iterationData.target_improvements.map((imp, idx) => (
                    <span key={idx} className="text-xs bg-cyan-100 text-cyan-700 px-2 py-1 rounded flex items-center gap-1">
                      {imp}
                      <button 
                        onClick={() => setIterationData({
                          ...iterationData,
                          target_improvements: iterationData.target_improvements.filter((_, i) => i !== idx)
                        })}
                        className="hover:text-red-500"
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
                <MessageSquare className="w-4 h-4 inline mr-1" />
                迭代将基于当前产出物创建新任务，生成改进后的版本。
              </div>

              <div className="flex gap-2 justify-end pt-4">
                <Button variant="outline" onClick={() => setSelectedOutput(null)}>取消</Button>
                <Button 
                  onClick={submitIteration} 
                  disabled={!iterationData.feedback || iterating}
                  className="bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50"
                >
                  {iterating ? (
                    <>
                      <RotateCw className="w-4 h-4 mr-2 animate-spin" />
                      迭代中...
                    </>
                  ) : (
                    <>
                      <RotateCw className="w-4 h-4 mr-2" />
                      开始迭代
                    </>
                  )}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 详情弹窗 */}
      {selectedOutput && modalMode === 'view' && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-[700px] max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">{selectedOutput.name}</h3>
              <button onClick={() => setSelectedOutput(null)} className="text-gray-500 hover:text-gray-700">✕</button>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-4 gap-3 text-sm">
                <div className="bg-gray-50 p-2 rounded">
                  <div className="text-xs text-gray-500">类型</div>
                  <div className={getTypeColor(selectedOutput.type)}>{selectedOutput.type}</div>
                </div>
                <div className="bg-gray-50 p-2 rounded">
                  <div className="text-xs text-gray-500">状态</div>
                  <div><Badge className={getStatusColor(selectedOutput.status)}>{getStatusText(selectedOutput.status)}</Badge></div>
                </div>
                <div className="bg-gray-50 p-2 rounded">
                  <div className="text-xs text-gray-500">版本</div>
                  <div>v{selectedOutput.iteration_count + 1}</div>
                </div>
                <div className="bg-gray-50 p-2 rounded">
                  <div className="text-xs text-gray-500">创建时间</div>
                  <div className="text-xs">{new Date(selectedOutput.created_at).toLocaleString('zh-CN')}</div>
                </div>
              </div>

              {selectedOutput.review && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Star className="w-4 h-4 text-yellow-500 fill-yellow-500" />
                    <span className="font-medium">评审信息</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>评分: {selectedOutput.review.rating}/5</div>
                    <div>状态: {selectedOutput.review.approved ? '已批准' : '未批准'}</div>
                    {selectedOutput.review.comments && (
                      <div className="col-span-2">意见: {selectedOutput.review.comments}</div>
                    )}
                    {selectedOutput.review.feedback && (
                      <div className="col-span-2">反馈: {selectedOutput.review.feedback}</div>
                    )}
                  </div>
                </div>
              )}

              {selectedOutput.files.length > 0 && (
                <div>
                  <h4 className="font-medium mb-2">文件列表 ({selectedOutput.files.length})</h4>
                  <div className="space-y-2">
                    {selectedOutput.files.map((file, idx) => (
                      <div key={idx} className="bg-gray-50 rounded-lg p-3">
                        <div className="flex items-center gap-2 mb-2">
                          {getFileIcon(file.type)}
                          <span className="text-sm font-medium">{file.path}</span>
                          <span className="text-xs text-gray-500 ml-auto">{file.lines} 行</span>
                        </div>
                        {file.preview && (
                          <pre className="bg-gray-900 text-gray-100 text-xs p-3 rounded overflow-x-auto max-h-40">
                            {file.preview}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedOutput.metadata?.output_preview && (
                <div>
                  <h4 className="font-medium mb-2">输出预览</h4>
                  <pre className="bg-gray-50 text-sm p-3 rounded overflow-x-auto max-h-40 whitespace-pre-wrap">
                    {selectedOutput.metadata.output_preview}
                  </pre>
                </div>
              )}

              <div className="flex gap-2 justify-end pt-4">
                <Button variant="outline" onClick={() => setSelectedOutput(null)}>关闭</Button>
                <Button onClick={() => setModalMode('review')} className="bg-orange-500 hover:bg-orange-600">
                  <Star className="w-4 h-4 mr-1" />
                  评审
                </Button>
                <Button onClick={() => setModalMode('iterate')} className="bg-cyan-500 hover:bg-cyan-600">
                  <RotateCw className="w-4 h-4 mr-1" />
                  迭代
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}