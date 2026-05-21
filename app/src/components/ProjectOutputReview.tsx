import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from 'sonner';
import { 
  FolderOpen, FileText, CheckCircle,
  Star, ChevronRight, File, Code
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
  metadata?: {
    task_id?: string;
    original_status?: string;
    performance?: { total_duration?: number; tokens_used?: number };
    layers?: string[];
    output_preview?: string;
  };
}

interface ReviewData {
  rating: number;
  comments: string;
  approved: boolean;
}

export function ProjectOutputReview() {
  const [outputs, setOutputs] = useState<ProjectOutput[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedOutput, setSelectedOutput] = useState<ProjectOutput | null>(null);
  const [reviewData, setReviewData] = useState<ReviewData>({ rating: 0, comments: '', approved: false });
  const [error, setError] = useState('');
  const [activeView, setActiveView] = useState<'all' | 'code' | 'docs'>('all');

  const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001';

  useEffect(() => {
    fetchOutputs();
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
      toast.success(`评审提交成功！批准状态: ${data.review.approved ? '已批准' : '未批准'}，评分: ${data.review.rating}星`);
      setSelectedOutput(null);
      setReviewData({ rating: 0, comments: '', approved: false });
      fetchOutputs();
    } catch (e: any) {
      toast.error(`评审提交失败: ${e.message}`);
    }
  };

  const getStatusColor = (status: string, originalStatus?: string) => {
    if (status === 'completed' || originalStatus === 'success') return 'bg-green-500';
    if (status === 'pending_review' || originalStatus === 'failed') return 'bg-yellow-500';
    if (status === 'in_progress') return 'bg-blue-500';
    return 'bg-gray-500';
  };

  const getStatusText = (status: string, originalStatus?: string) => {
    if (status === 'completed' || originalStatus === 'success') return '已完成';
    if (status === 'pending_review' || originalStatus === 'failed') return '待评审';
    if (status === 'in_progress') return '进行中';
    return status;
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
        <Button onClick={fetchOutputs} variant="outline" size="sm">
          刷新
        </Button>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-4 gap-3">
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
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
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
                    onClick={() => setSelectedOutput(output)}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm truncate flex-1">{output.name}</CardTitle>
                    <Badge className={getStatusColor(output.status, output.metadata?.original_status)}>
                      {getStatusText(output.status, output.metadata?.original_status)}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500 mt-1">
                    <span className={`font-medium ${getTypeColor(output.type)}`}>
                      {output.type.replace(/_/g, ' ')}
                    </span>
                    <span>|</span>
                    <span>{output.created_at}</span>
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
                  {output.metadata?.layers && (
                    <div className="flex gap-1 mt-2">
                      {output.metadata.layers.map((layer, idx) => (
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
                        <span className="text-xs text-gray-500">+{output.files.length - 3} more</span>
                      )}
                    </div>
                  )}
                  <div className="mt-2 flex items-center justify-between">
                    <span className="text-[10px] text-gray-400">
                      {output.metadata?.performance?.tokens_used || 0} tokens
                    </span>
                    <ChevronRight className="w-4 h-4 text-gray-400" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </ScrollArea>
      )}

      {/* 评审弹窗 */}
      {selectedOutput && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-[600px] max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">评审产出物: {selectedOutput.name}</h3>
              <button onClick={() => setSelectedOutput(null)} className="text-gray-500 hover:text-gray-700">✕</button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">产出物详情</label>
                <div className="bg-gray-50 rounded-lg p-3 text-sm">
                  <div className="grid grid-cols-2 gap-2 mb-3">
                    <div>ID: {selectedOutput.id}</div>
                    <div>类型: {selectedOutput.type}</div>
                    <div>状态: {getStatusText(selectedOutput.status)}</div>
                    <div>创建时间: {selectedOutput.created_at}</div>
                  </div>
                  <div className="mb-2 font-medium">文件列表:</div>
                  {selectedOutput.files.map((file, idx) => (
                    <div key={idx} className="flex items-center gap-2 text-xs ml-2">
                      {getFileIcon(file.type)}
                      <span>{file.path}</span>
                      <span className="text-gray-500">({file.lines} 行)</span>
                    </div>
                  ))}
                  {selectedOutput.tests.length > 0 && (
                    <>
                      <div className="mb-2 font-medium mt-3">测试列表:</div>
                      {selectedOutput.tests.map((test, idx) => (
                        <div key={idx} className="flex items-center gap-2 text-xs ml-2">
                          <CheckCircle className="w-3 h-3 text-green-500" />
                          <span>{test.path}</span>
                          <span className="text-gray-500">({test.status})</span>
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
    </div>
  );
}