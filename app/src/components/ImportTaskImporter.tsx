import { useState, useRef, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import {
  FileText, Upload, CheckCircle, AlertCircle, RefreshCw,
  Play, Download, Eye, FileCode, Braces,
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8011';

interface ItdDocument {
  metadata: Record<string, unknown>;
  summary: string;
  requirements: unknown[];
  deliverable_contract: Record<string, unknown>;
  kill_criteria: unknown[];
  resource_budget: Record<string, unknown>;
  context: Record<string, unknown>;
  related_documents: unknown[];
}

interface ValidationIssue {
  type: string;
  message: string;
}

export function ImportTaskImporter() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState('input');
  const [markdown, setMarkdown] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [parsed, setParsed] = useState<ItdDocument | null>(null);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [valid, setValid] = useState<boolean | null>(null);
  const [importResult, setImportResult] = useState<string>('');
  const fileRef = useRef<HTMLInputElement>(null);

  const apiCall = useCallback(async (path: string, body: unknown) => {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return res.json();
  }, []);

  const handleParse = useCallback(async () => {
    if (!markdown.trim()) { setError('请输入 ITD Markdown'); return; }
    setLoading(true); setError(''); setParsed(null); setIssues([]); setValid(null); setImportResult('');
    try {
      const data = await apiCall('/api/v1/tasks/itd/parse', { content: markdown });
      if (data.status === 'failed') { setError(data.error); return; }
      setParsed(data.document);
      if (data.warnings?.length) setIssues(data.warnings.map((w: string) => ({ type: 'warning', message: w })));
      setTab('result');
    } catch (e) { setError(e instanceof Error ? e.message : 'Parse failed'); }
    finally { setLoading(false); }
  }, [markdown, apiCall]);

  const handleValidate = useCallback(async () => {
    if (!markdown.trim()) { setError('请输入 ITD Markdown'); return; }
    setLoading(true); setError(''); setParsed(null); setImportResult('');
    try {
      const data = await apiCall('/api/v1/tasks/itd/validate', { content: markdown });
      if (data.status === 'failed') { setError(data.error); return; }
      setIssues(data.issues || []);
      setValid(data.valid);
      setTab('result');
    } catch (e) { setError(e instanceof Error ? e.message : 'Validate failed'); }
    finally { setLoading(false); }
  }, [markdown, apiCall]);

  const handleImport = useCallback(async () => {
    if (!markdown.trim()) { setError('请输入 ITD Markdown'); return; }
    setLoading(true); setError(''); setImportResult('');
    try {
      const data = await apiCall('/api/v1/tasks/itd/import', { content: markdown, auto_start: false });
      if (data.status === 'failed') { setError(data.error); return; }
      setImportResult(`Task created: ${data.task.title} (${data.task.task_id})`);
      setTab('result');
    } catch (e) { setError(e instanceof Error ? e.message : 'Import failed'); }
    finally { setLoading(false); }
  }, [markdown, apiCall]);

  const handleFile = useCallback(async (files: FileList | null) => {
    if (!files?.length) return;
    const text = await files[0].text();
    setMarkdown(text);
  }, []);

  const loadTemplate = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/tasks/itd/templates`);
      const data = await res.json();
      const tmpl = data.templates?.find((t: { id: string }) => t.id === id);
      if (tmpl) setMarkdown(tmpl.template);
    } catch { setError('Failed to load template'); }
    finally { setLoading(false); }
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <FileCode className="w-4 h-4" />
          ITD 导入
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Braces className="w-5 h-5 text-purple-500" />
            Import Task Document 导入器
          </DialogTitle>
        </DialogHeader>

        <Tabs value={tab} onValueChange={setTab} className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="grid grid-cols-3 mb-4">
            <TabsTrigger value="input" className="text-xs gap-1">
              <FileText className="w-3 h-3" /> 输入
            </TabsTrigger>
            <TabsTrigger value="result" className="text-xs gap-1">
              <Eye className="w-3 h-3" /> 结果
            </TabsTrigger>
            <TabsTrigger value="generate" className="text-xs gap-1">
              <Download className="w-3 h-3" /> 生成
            </TabsTrigger>
          </TabsList>

          <TabsContent value="input" className="flex-1 flex flex-col overflow-hidden space-y-3">
            <div className="flex items-center gap-2 flex-wrap">
              <input ref={fileRef} type="file" accept=".task.md,.md" onChange={(e) => handleFile(e.target.files)} className="hidden" />
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <Upload className="w-3 h-3 mr-1" /> 上传 .task.md
              </Button>
              <Button variant="ghost" size="sm" onClick={() => loadTemplate('code')}>代码模板</Button>
              <Button variant="ghost" size="sm" onClick={() => loadTemplate('architecture')}>架构模板</Button>
              <Button variant="ghost" size="sm" onClick={() => loadTemplate('analysis')}>分析模板</Button>
            </div>
            <Textarea
              value={markdown}
              onChange={(e) => setMarkdown(e.target.value)}
              placeholder="粘贴 ITD Markdown 内容..."
              className="flex-1 min-h-[300px] font-mono text-xs"
            />
            {error && (
              <div className="flex items-center gap-2 text-red-500 text-xs p-2 bg-red-50 rounded">
                <AlertCircle className="w-3 h-3" /> {error}
              </div>
            )}
            <div className="flex items-center gap-2">
              <Button onClick={handleParse} disabled={loading} className="gap-2 bg-purple-600 hover:bg-purple-700">
                {loading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Eye className="w-3 h-3" />}
                解析
              </Button>
              <Button onClick={handleValidate} disabled={loading} variant="outline" className="gap-2">
                <CheckCircle className="w-3 h-3" /> 验证
              </Button>
              <Button onClick={handleImport} disabled={loading} variant="outline" className="gap-2">
                <Play className="w-3 h-3" /> 导入
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="result" className="flex-1 overflow-y-auto space-y-3">
            {parsed && (
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">解析结果</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div><span className="text-gray-400">标题:</span> {String(parsed.metadata?.title || '')}</div>
                    <div><span className="text-gray-400">类型:</span> {String(parsed.metadata?.type || '')}</div>
                    <div><span className="text-gray-400">优先级:</span> {String(parsed.metadata?.priority || '')}</div>
                    <div><span className="text-gray-400">交付类型:</span> {String(parsed.metadata?.deliverable_kind || '')}</div>
                  </div>
                  <div className="text-xs"><span className="text-gray-400">概要:</span> {parsed.summary?.slice(0, 200)}</div>
                  <div className="flex gap-2 flex-wrap">
                    <Badge variant="outline" className="text-xs">{Array.isArray(parsed.requirements) ? parsed.requirements.length : 0} 需求</Badge>
                    <Badge variant="outline" className="text-xs">{Array.isArray(parsed.kill_criteria) ? parsed.kill_criteria.length : 0} 终止条件</Badge>
                    <Badge variant="outline" className="text-xs">{Array.isArray((parsed.deliverable_contract as Record<string, unknown>).acceptance_criteria) ? ((parsed.deliverable_contract as Record<string, unknown>).acceptance_criteria as unknown[]).length : 0} 验收标准</Badge>
                  </div>
                  <details className="text-xs">
                    <summary className="cursor-pointer text-gray-500">完整 JSON</summary>
                    <pre className="mt-2 p-2 bg-gray-50 rounded overflow-x-auto max-h-60">{JSON.stringify(parsed, null, 2)}</pre>
                  </details>
                </CardContent>
              </Card>
            )}
            {valid !== null && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    {valid ? <CheckCircle className="w-4 h-4 text-green-500" /> : <AlertCircle className="w-4 h-4 text-red-500" />}
                    验证结果: {valid ? '通过' : '失败'}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {issues.length > 0 ? (
                    <div className="space-y-1">
                      {issues.map((iss, i) => (
                        <div key={i} className={`text-xs p-1.5 rounded flex items-center gap-1 ${
                          iss.type === 'error' ? 'bg-red-50 text-red-700' :
                          iss.type === 'warning' ? 'bg-yellow-50 text-yellow-700' : 'bg-blue-50 text-blue-700'
                        }`}>
                          <Badge className="text-[8px]">{iss.type}</Badge> {iss.message}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-green-600">无问题</p>
                  )}
                </CardContent>
              </Card>
            )}
            {importResult && (
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">导入结果</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-xs text-green-600">{importResult}</p>
                </CardContent>
              </Card>
            )}
            {!parsed && valid === null && !importResult && (
              <div className="text-center py-8 text-gray-400">
                <Eye className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p className="text-xs">点击"解析"、"验证"或"导入"查看结果</p>
              </div>
            )}
          </TabsContent>

          <TabsContent value="generate" className="flex-1 overflow-y-auto space-y-3">
            <GenerateForm onGenerated={(md) => { setMarkdown(md); setTab('input'); }} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function GenerateForm({ onGenerated }: { onGenerated: (md: string) => void }) {
  const [title, setTitle] = useState('');
  const [type, setType] = useState('code_generation');
  const [priority, setPriority] = useState('medium');
  const [summary, setSummary] = useState('');
  const [kind, setKind] = useState('code');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleGenerate = useCallback(async () => {
    if (!title.trim()) { setError('请输入标题'); return; }
    setLoading(true); setError('');
    try {
      const res = await fetch(`${API_BASE}/api/v1/tasks/itd/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          version: '1.0.0',
          author: 'ITD Importer',
          type,
          priority,
          deliverable_kind: kind,
          tags: [type],
          summary: summary.trim(),
          required_dimensions: ['core_output', 'reasoning'],
        }),
      });
      const data = await res.json();
      if (data.status === 'failed') { setError(data.error); return; }
      onGenerated(data.markdown);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Generation failed');
    } finally { setLoading(false); }
  }, [title, type, priority, summary, kind, onGenerated]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Download className="w-4 h-4 text-purple-500" />
          生成 ITD Markdown
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1">标题</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Task title" className="text-xs" />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">类型</label>
            <select value={type} onChange={(e) => setType(e.target.value)} className="w-full text-xs border rounded px-2 py-1.5">
              <option value="code_generation">Code Generation</option>
              <option value="architecture_design">Architecture Design</option>
              <option value="data_analysis">Data Analysis</option>
              <option value="nlp_task">NLP Task</option>
              <option value="code_debugging">Code Debugging</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">优先级</label>
            <select value={priority} onChange={(e) => setPriority(e.target.value)} className="w-full text-xs border rounded px-2 py-1.5">
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">交付类型</label>
            <select value={kind} onChange={(e) => setKind(e.target.value)} className="w-full text-xs border rounded px-2 py-1.5">
              <option value="code">Code</option>
              <option value="architecture">Architecture</option>
              <option value="analysis">Analysis</option>
              <option value="documentation">Documentation</option>
            </select>
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">概要</label>
          <Textarea value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="Task summary" className="min-h-[60px] text-xs" />
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
        <Button onClick={handleGenerate} disabled={loading} className="w-full gap-2 bg-purple-600 hover:bg-purple-700">
          {loading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <FileCode className="w-3 h-3" />}
          生成并填入
        </Button>
      </CardContent>
    </Card>
  );
}
