import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import type { DashboardData } from '@/types/morev3';
import { Brain, BookOpen, Lightbulb, History, Star, Search, Tag, HardDrive, BarChart3 } from 'lucide-react';
import { NumberPrecision, formatTimestamp } from '@/lib/format';

interface MemoryPanelProps {
  data: DashboardData;
}

const MEMORY_CAPACITY = 2048;

export function MemoryPanel({ data }: MemoryPanelProps) {
  const { memorySystem } = data;
  const [searchQuery, setSearchQuery] = useState('');

  const totalMemories = memorySystem.episodic.length + memorySystem.semantic.length + memorySystem.procedural.length;
  const avgRelevance = totalMemories > 0
    ? [...memorySystem.episodic, ...memorySystem.semantic, ...memorySystem.procedural]
      .reduce((sum, m) => sum + m.relevance, 0) / totalMemories
    : 0;

  const capacityUsage = (totalMemories / MEMORY_CAPACITY) * 100;

  const allMemories = [...memorySystem.episodic, ...memorySystem.semantic, ...memorySystem.procedural];
  const searchResults = searchQuery
    ? allMemories.filter(m => m.content.toLowerCase().includes(searchQuery.toLowerCase()))
    : [];

  const extractTags = (memories: DashboardData['memorySystem']['episodic']) => {
    const tagCounts: Record<string, number> = {};
    memories.forEach(m => {
      const matches = m.content.match(/#\w+/g);
      if (matches) {
        matches.forEach(tag => {
          tagCounts[tag] = (tagCounts[tag] || 0) + 1;
        });
      }
    });
    return Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).slice(0, 5);
  };

  const episodicTags = extractTags(memorySystem.episodic);
  const semanticTags = extractTags(memorySystem.semantic);
  const proceduralTags = extractTags(memorySystem.procedural);

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
        <Brain className="w-5 h-5 text-orange-600" />
        记忆系统
      </h3>

      {/* 搜索框 */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <Input
          placeholder="搜索记忆..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          className="pl-9 h-8 text-xs"
        />
        {searchQuery && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-white border rounded-lg shadow-lg z-10 max-h-48 overflow-auto">
            {searchResults.length > 0 ? (
              searchResults.slice(0, 10).map(m => (
                <div key={m.id} className="p-2 hover:bg-gray-50 text-xs cursor-pointer" onClick={() => setSearchQuery('')}>
                  <span className="text-gray-600 truncate block">{m.content}</span>
                  <Badge variant="outline" className="text-[8px] mt-1">{m.type}</Badge>
                </div>
              ))
            ) : (
              <p className="p-2 text-xs text-gray-400">无匹配结果</p>
            )}
          </div>
        )}
      </div>

      {/* 统计 */}
      <div className="grid grid-cols-3 gap-2">
        <Card className="bg-blue-50 border-blue-200">
          <CardContent className="p-2 text-center">
            <History className="w-4 h-4 text-blue-600 mx-auto mb-1" />
            <p className="text-lg font-bold">{memorySystem.episodic.length}</p>
            <p className="text-[10px] text-gray-500">情景记忆</p>
          </CardContent>
        </Card>
        <Card className="bg-green-50 border-green-200">
          <CardContent className="p-2 text-center">
            <BookOpen className="w-4 h-4 text-green-600 mx-auto mb-1" />
            <p className="text-lg font-bold">{memorySystem.semantic.length}</p>
            <p className="text-[10px] text-gray-500">语义记忆</p>
          </CardContent>
        </Card>
        <Card className="bg-purple-50 border-purple-200">
          <CardContent className="p-2 text-center">
            <Lightbulb className="w-4 h-4 text-purple-600 mx-auto mb-1" />
            <p className="text-lg font-bold">{memorySystem.procedural.length}</p>
            <p className="text-[10px] text-gray-500">程序记忆</p>
          </CardContent>
        </Card>
      </div>

      {/* 容量状态 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-gray-500" />
            存储容量
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-500">已使用</span>
              <span className="font-medium">{totalMemories} / {MEMORY_CAPACITY}</span>
            </div>
            <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  capacityUsage > 80 ? 'bg-red-500' : capacityUsage > 60 ? 'bg-yellow-500' : 'bg-green-500'
                }`}
                style={{ width: `${Math.min(capacityUsage, 100)}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-gray-400">
              <span>{capacityUsage.toFixed(1)}% 已用</span>
              <span>{MEMORY_CAPACITY - totalMemories} 可用</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 统计图表 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-gray-500" />
            访问统计
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-gray-500">总记忆条目</span>
                <span className="font-medium">{totalMemories}</span>
              </div>
              <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-blue-500 via-green-500 to-purple-500 rounded-full" style={{ width: `${(totalMemories / MEMORY_CAPACITY) * 100}%` }} />
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-gray-500">平均相关性</span>
                <span className="font-medium">{(avgRelevance * 100).toFixed(0)}%</span>
              </div>
              <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                <div className="h-full bg-orange-500 rounded-full" style={{ width: `${avgRelevance * 100}%` }} />
              </div>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-4 text-[10px] text-gray-400">
            <span>情景 {memorySystem.episodic.reduce((s, m) => s + m.accessCount, 0)} 访问</span>
            <span>语义 {memorySystem.semantic.reduce((s, m) => s + m.accessCount, 0)} 访问</span>
            <span>程序 {memorySystem.procedural.reduce((s, m) => s + m.accessCount, 0)} 访问</span>
          </div>
        </CardContent>
      </Card>

      {/* 记忆列表 */}
      <Tabs defaultValue="episodic" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="episodic" className="text-xs">
            <History className="w-3 h-3 mr-1" /> 情景
          </TabsTrigger>
          <TabsTrigger value="semantic" className="text-xs">
            <BookOpen className="w-3 h-3 mr-1" /> 语义
          </TabsTrigger>
          <TabsTrigger value="procedural" className="text-xs">
            <Lightbulb className="w-3 h-3 mr-1" /> 程序
          </TabsTrigger>
        </TabsList>

        <TabsContent value="episodic">
          <MemoryListWithTags
            memories={memorySystem.episodic}
            color="blue"
            tags={episodicTags}
          />
        </TabsContent>
        <TabsContent value="semantic">
          <MemoryListWithTags
            memories={memorySystem.semantic}
            color="green"
            tags={semanticTags}
          />
        </TabsContent>
        <TabsContent value="procedural">
          <MemoryListWithTags
            memories={memorySystem.procedural}
            color="purple"
            tags={proceduralTags}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function MemoryListWithTags({
  memories,
  color,
  tags,
}: {
  memories: DashboardData['memorySystem']['episodic'];
  color: string;
  tags: [string, number][];
}) {
  const colorMap: Record<string, { bg: string; border: string; badge: string; accent: string }> = {
    blue: { bg: 'bg-blue-50', border: 'border-blue-100', badge: 'bg-blue-500', accent: 'text-blue-600' },
    green: { bg: 'bg-green-50', border: 'border-green-100', badge: 'bg-green-500', accent: 'text-green-600' },
    purple: { bg: 'bg-purple-50', border: 'border-purple-100', badge: 'bg-purple-500', accent: 'text-purple-600' },
  };
  const c = colorMap[color];

  return (
    <div className="space-y-3">
      {tags.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <Tag className="w-3 h-3 text-gray-400" />
          {tags.map(([tag, count]) => (
            <Badge key={tag} variant="outline" className="text-[8px] h-4">
              {tag} ({count})
            </Badge>
          ))}
        </div>
      )}
      <ScrollArea className="h-64">
        <div className="space-y-2">
          {memories.map(memory => (
            <MemoryCard key={memory.id} memory={memory} c={c} />
          ))}
          {memories.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-8">暂无记忆条目</p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

function MemoryCard({
  memory,
  c,
}: {
  memory: DashboardData['memorySystem']['episodic'][0];
  c: { bg: string; border: string; badge: string; accent: string };
}) {
  const contentTags = memory.content.match(/#\w+/g) || [];

  return (
    <div className={`${c.bg} ${c.border} border rounded-lg p-2.5`}>
      <div className="flex items-start justify-between">
        <p className="text-xs text-gray-700 flex-1">{memory.content}</p>
        <Badge className={`${c.badge} text-[8px] h-4 ml-2 flex-shrink-0`}>
          {NumberPrecision.percentage(memory.relevance)}%
        </Badge>
      </div>
      {contentTags.length > 0 && (
        <div className="flex items-center gap-1 mt-1.5 flex-wrap">
          {contentTags.slice(0, 3).map(tag => (
            <span key={tag} className={`text-[9px] ${c.accent}`}>{tag}</span>
          ))}
        </div>
      )}
      <div className="flex items-center gap-3 mt-1.5 text-[9px] text-gray-400">
        <span className="flex items-center gap-1">
          <Star className="w-2.5 h-2.5" />
          {NumberPrecision.count(memory.accessCount)}次
        </span>
        <span>{formatTimestamp(memory.timestamp, 'date')}</span>
        {memory.embedding && memory.embedding.length > 0 && (
          <Badge variant="outline" className="text-[8px] h-3">
            {NumberPrecision.count(memory.embedding.length)}维
          </Badge>
        )}
      </div>
    </div>
  );
}