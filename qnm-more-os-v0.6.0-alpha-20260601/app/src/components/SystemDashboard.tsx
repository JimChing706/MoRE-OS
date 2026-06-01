import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { 
  Activity, TrendingUp, Clock, AlertTriangle, 
  Layers, Cpu, GitBranch
} from 'lucide-react';
import type { DashboardData } from '@/types/morev3';
import { NumberPrecision } from '@/lib/format';

interface SystemDashboardProps {
  data: DashboardData;
}

export function SystemDashboard({ data }: SystemDashboardProps) {
  const { t } = useTranslation();
  const { systemState, layerMetrics, evolutionStats } = data;
  const [prevThroughput, setPrevThroughput] = useState(systemState.throughput);
  const [throughputTrend, setThroughputTrend] = useState(0);

  useEffect(() => {
    setThroughputTrend(systemState.throughput - prevThroughput);
    setPrevThroughput(systemState.throughput);
  }, [systemState.throughput]);

  const statusColor = {
    running: 'bg-green-500',
    initializing: 'bg-yellow-500',
    degraded: 'bg-orange-500',
    maintenance: 'bg-blue-500',
  };

  const criticalEvents = data.safetyEvents.filter(e => e.severity === 'critical' || e.severity === 'high');

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Card className="border-l-4 border-l-green-500">
          <CardContent className="p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-gray-500">{t('dashboard.systemStatus')}</p>
                <div className="flex items-center gap-2 mt-1">
                  <div className={`w-2.5 h-2.5 rounded-full ${statusColor[systemState.status]}`} />
                  <span className="text-sm font-bold text-gray-800">
                    {t('app.status.' + systemState.status)}
                  </span>
                </div>
              </div>
              <Activity className="w-8 h-8 text-green-500" />
            </div>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-blue-500">
          <CardContent className="p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-gray-500">{t('dashboard.throughput')}</p>
                <div className="flex items-center gap-1 mt-1">
                  <span className="text-lg font-bold text-gray-800">{NumberPrecision.count(systemState.throughput)}</span>
                  <span className="text-xs text-gray-400">/min</span>
                </div>
                {throughputTrend !== 0 && (
                  <span className={`text-[10px] ${throughputTrend > 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {throughputTrend > 0 ? '+' : ''}{NumberPrecision.count(throughputTrend)}
                  </span>
                )}
              </div>
              <TrendingUp className="w-8 h-8 text-blue-500" />
            </div>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-orange-500">
          <CardContent className="p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-gray-500">{t('dashboard.avgLatency')}</p>
                <div className="flex items-center gap-1 mt-1">
                  <span className="text-lg font-bold text-gray-800">{NumberPrecision.count(systemState.avgLatency)}</span>
                  <span className="text-xs text-gray-400">ms</span>
                </div>
              </div>
              <Clock className="w-8 h-8 text-orange-500" />
            </div>
          </CardContent>
        </Card>

        <Card className={`border-l-4 ${criticalEvents.length > 0 ? 'border-l-red-500' : 'border-l-green-500'}`}>
          <CardContent className="p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-gray-500">{t('dashboard.safetyEvents')}</p>
                <div className="flex items-center gap-1 mt-1">
                  <span className={`text-lg font-bold ${criticalEvents.length > 0 ? 'text-red-600' : 'text-gray-800'}`}>
                    {NumberPrecision.count(criticalEvents.length)}
                  </span>
                  <span className="text-xs text-gray-400">{t('dashboard.pending')}</span>
                </div>
              </div>
              <AlertTriangle className={`w-8 h-8 ${criticalEvents.length > 0 ? 'text-red-500' : 'text-green-500'}`} />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Layers className="w-4 h-4" />
              {t('dashboard.runtimeOverview')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.activeTasks')}</span>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold">{NumberPrecision.count(systemState.activeTasks)}</span>
                <div className="w-20 h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.min(100, systemState.activeTasks * 5)}%` }} />
                </div>
              </div>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.queuedTasks')}</span>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold">{NumberPrecision.count(systemState.queuedTasks)}</span>
                <div className="w-20 h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div className="h-full bg-yellow-500 rounded-full" style={{ width: `${Math.min(100, systemState.queuedTasks * 10)}%` }} />
                </div>
              </div>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.errorRate')}</span>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold">{NumberPrecision.percentage(systemState.errorRate)}%</span>
                <div className="w-20 h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div 
                    className={`h-full rounded-full ${systemState.errorRate > 0.05 ? 'bg-red-500' : 'bg-green-500'}`} 
                    style={{ width: `${Math.min(100, systemState.errorRate * 500)}%` }} 
                  />
                </div>
              </div>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.activeLayers')}</span>
              <span className="text-sm font-bold">{NumberPrecision.count(systemState.activeLayers.length)} / 6</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <GitBranch className="w-4 h-4" />
              {t('dashboard.evolutionStatus')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.evolutionArchive')}</span>
              <Badge variant="outline" className="font-mono">{NumberPrecision.count(evolutionStats.totalAgents)} agents</Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.activeBranches')}</span>
              <Badge variant="outline" className="font-mono">{NumberPrecision.count(evolutionStats.totalBranches)} branches</Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.bestScore')}</span>
              <Badge className="bg-orange-500 font-mono">{NumberPrecision.score(evolutionStats.currentBestScore)}%</Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.improvementRate')}</span>
              <span className="text-sm font-bold text-green-600">+{NumberPrecision.percentage(evolutionStats.improvementRate)}%/iter</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">{t('dashboard.convergenceStatus')}</span>
              <Badge className={`${
                evolutionStats.convergenceStatus === 'exploring' ? 'bg-blue-500' :
                evolutionStats.convergenceStatus === 'converging' ? 'bg-yellow-500' :
                evolutionStats.convergenceStatus === 'converged' ? 'bg-green-500' : 'bg-red-500'
              }`}>
                {t('dashboard.' + evolutionStats.convergenceStatus)}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Cpu className="w-4 h-4" />
            {t('dashboard.engineLoad')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {layerMetrics.map(metric => {
              const colorMap: Record<string, string> = {
                L0: '#FFD54F', L1: '#FFC107', L2: '#FFB300',
                L3: '#FFA000', L4: '#FF8F00', L5: '#FF6F00',
              };
              return (
                <div key={metric.layerId} className="flex items-center gap-3">
                  <span className="text-xs font-mono w-6">{metric.layerId}</span>
                  <span className="text-xs text-gray-600 w-16 truncate">{metric.layerName}</span>
                  <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden">
                    <div 
                      className="h-full rounded-full transition-all duration-500"
                      style={{ 
                        width: `${NumberPrecision.decimal(metric.engineUtilization * 100, 0)}%`,
                        backgroundColor: colorMap[metric.layerId],
                      }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 w-12 text-right">
                    {NumberPrecision.percentage(metric.engineUtilization)}%
                  </span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}