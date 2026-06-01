import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { DashboardData, EvolvedAgent, EvolutionBranch, EvolutionArchive } from '@/types/morev3';
import { GitBranch, GitCommit, Trophy, TrendingUp, Clock, Dna, Activity } from 'lucide-react';

interface EvolutionBrowserProps {
  data: DashboardData;
}

export function EvolutionBrowser({ data }: EvolutionBrowserProps) {
  const { evolutionStats, systemState } = data;
  const archive = systemState.evolutionArchive;
  const bestAgent = archive.agents.reduce((a, b) => a.performance > b.performance ? a : b);

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
        <Dna className="w-5 h-5 text-orange-600" />
        DGM 进化归档浏览器
      </h3>

      {/* 统计概览 */}
      <div className="grid grid-cols-2 gap-3">
        <Card className="bg-gradient-to-br from-orange-50 to-amber-50 border-orange-200">
          <CardContent className="p-3">
            <div className="flex items-center gap-2">
              <Trophy className="w-5 h-5 text-orange-600" />
              <div>
                <p className="text-[10px] text-gray-500">当前最优</p>
                <p className="text-lg font-bold text-orange-700">{(bestAgent.performance * 100).toFixed(1)}%</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-purple-50 to-pink-50 border-purple-200">
          <CardContent className="p-3">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-purple-600" />
              <div>
                <p className="text-[10px] text-gray-500">改进速率</p>
                <p className="text-lg font-bold text-purple-700">+{(evolutionStats.improvementRate * 100).toFixed(2)}%</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="agents" className="w-full">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="agents" className="text-xs">
            <GitCommit className="w-3 h-3 mr-1" /> 进化谱系
          </TabsTrigger>
          <TabsTrigger value="branches" className="text-xs">
            <GitBranch className="w-3 h-3 mr-1" /> 分支管理
          </TabsTrigger>
        </TabsList>

        <TabsContent value="agents">
          <ScrollArea className="h-80">
            <div className="space-y-2">
              {/* 进化树可视化 */}
              <div className="relative p-3 bg-gray-50 rounded-lg">
                <h4 className="text-xs font-medium text-gray-500 mb-3">进化时间线</h4>
                <div className="space-y-2">
                  {archive.agents.slice(-15).reverse().map((agent) => (
                    <AgentTimelineItem 
                      key={agent.id} 
                      agent={agent} 
                      isBest={agent.id === bestAgent.id}
                    />
                  ))}
                </div>
              </div>
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="branches">
          <ScrollArea className="h-80">
            <div className="space-y-2">
              {archive.branches.map(branch => (
                <BranchCard key={branch.id} branch={branch} archive={archive} />
              ))}
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>

      {/* 收敛状态 */}
      <Card className={`border-l-4 ${
        evolutionStats.convergenceStatus === 'exploring' ? 'border-l-blue-500' :
        evolutionStats.convergenceStatus === 'converging' ? 'border-l-yellow-500' :
        evolutionStats.convergenceStatus === 'converged' ? 'border-l-green-500' : 'border-l-red-500'
      }`}>
        <CardContent className="p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className={`w-4 h-4 ${
                evolutionStats.convergenceStatus === 'exploring' ? 'text-blue-500' :
                evolutionStats.convergenceStatus === 'converging' ? 'text-yellow-500' :
                evolutionStats.convergenceStatus === 'converged' ? 'text-green-500' : 'text-red-500'
              }`} />
              <div>
                <p className="text-xs text-gray-500">收敛状态</p>
                <p className="text-sm font-bold capitalize">{evolutionStats.convergenceStatus}</p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-500">活跃突变</p>
              <Badge variant="outline" className="font-mono">{evolutionStats.activeMutations}</Badge>
            </div>
          </div>
          {/* 进度指示 */}
          <div className="mt-2">
            <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div 
                className="h-full rounded-full transition-all duration-1000"
                style={{ 
                  width: `${Math.min(100, bestAgent.performance * 100)}%`,
                  backgroundColor: evolutionStats.convergenceStatus === 'exploring' ? '#3B82F6' :
                                  evolutionStats.convergenceStatus === 'converging' ? '#F59E0B' : '#22C55E',
                }}
              />
            </div>
            <p className="text-[10px] text-gray-400 mt-1 text-right">
              {(bestAgent.performance * 100).toFixed(1)}% / 100% 目标
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function AgentTimelineItem({ agent, isBest }: { agent: EvolvedAgent; isBest: boolean }) {
  const perfPercent = agent.performance * 100;
  const barColor = perfPercent > 60 ? '#22C55E' : perfPercent > 40 ? '#F59E0B' : '#EF4444';
  
  return (
    <div className={`flex items-center gap-2 p-2 rounded ${isBest ? 'bg-orange-50 border border-orange-200' : 'bg-white'}`}>
      <div className="w-8 text-[10px] text-gray-400 font-mono text-right">g{agent.generation}</div>
      <div className="flex-1">
        <div className="flex items-center gap-1">
          <span className="text-[10px] font-mono text-gray-600 truncate">{agent.id.slice(0, 12)}...</span>
          {isBest && <Trophy className="w-3 h-3 text-orange-500" />}
          {agent.mutations[0]?.verified ? 
            <Badge className="text-[8px] bg-green-500 h-4 px-1">已验证</Badge> :
            <Badge variant="outline" className="text-[8px] h-4 px-1">待验证</Badge>
          }
        </div>
        <div className="flex items-center gap-1 mt-0.5">
          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div 
              className="h-full rounded-full" 
              style={{ width: `${Math.min(100, perfPercent)}%`, backgroundColor: barColor }}
            />
          </div>
          <span className="text-[10px] font-mono w-10 text-right">{perfPercent.toFixed(1)}%</span>
        </div>
      </div>
      <div className="text-[9px] text-gray-400">
        <Clock className="w-2.5 h-2.5 inline mr-0.5" />
        {new Date(agent.createdAt).toLocaleTimeString()}
      </div>
    </div>
  );
}

function BranchCard({ branch, archive }: { branch: EvolutionBranch; archive: EvolutionArchive }) {
  const branchAgents = archive.agents.filter(a => a.branch === branch.id);
  const bestInBranch = branchAgents.reduce((a, b) => a.performance > b.performance ? a : b, branchAgents[0]);
  
  return (
    <Card className={`${branch.isActive ? 'border-blue-200' : 'border-gray-200 opacity-60'}`}>
      <CardContent className="p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <GitBranch className={`w-4 h-4 ${branch.isActive ? 'text-blue-500' : 'text-gray-400'}`} />
            <span className="text-sm font-medium">{branch.name}</span>
          </div>
          <Badge variant={branch.isActive ? 'default' : 'secondary'} className="text-[10px]">
            {branch.isActive ? '活跃' : '归档'}
          </Badge>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="bg-gray-50 rounded p-1">
            <p className="text-[10px] text-gray-400">Agents</p>
            <p className="text-sm font-bold">{branch.agentCount}</p>
          </div>
          <div className="bg-gray-50 rounded p-1">
            <p className="text-[10px] text-gray-400">最优</p>
            <p className="text-sm font-bold text-green-600">{(branch.bestPerformance * 100).toFixed(1)}%</p>
          </div>
          <div className="bg-gray-50 rounded p-1">
            <p className="text-[10px] text-gray-400">代数</p>
            <p className="text-sm font-bold">{bestInBranch?.generation || 0}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
