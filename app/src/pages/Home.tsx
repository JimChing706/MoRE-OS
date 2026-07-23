import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { LayerVisualizer } from '@/components/LayerVisualizer';
import { SystemDashboard } from '@/components/SystemDashboard';
import { TaskPanel } from '@/components/TaskPanel';
import { EvolutionBrowser } from '@/components/EvolutionBrowser';
import { SafetyPanel } from '@/components/SafetyPanel';
import { MemoryPanel } from '@/components/MemoryPanel';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { RequirementsImporter } from '@/components/RequirementsImporter';
import { ImportTaskImporter } from '@/components/ImportTaskImporter';
import { ProjectOutputReview } from '@/components/ProjectOutputReview';
import { moreEngine, getDashboardData } from '@/core/moreEngine';
import { useApiHealth } from '@/hooks/useApiHealth';
import { NumberPrecision, formatDuration } from '@/lib/format';
import type { DashboardData, LayerId } from '@/types/morev3';
import { 
  Cpu, GitBranch, ShieldCheck, Brain, 
  Terminal, Radio, BarChart3, Gamepad2, FolderOpen
} from 'lucide-react';

export default function Home() {
  const { t } = useTranslation();
  const { version } = useApiHealth();
  const [data, setData] = useState<DashboardData>(getDashboardData());
  const [selectedLayer, setSelectedLayer] = useState<LayerId | null>(null);
  const [activeTab, setActiveTab] = useState('overview');

  useEffect(() => {
    moreEngine.startSimulation(3000);
    const unsub = moreEngine.onUpdate((newData) => {
      setData(newData);
    });
    return () => {
      moreEngine.stopSimulation();
      unsub();
    };
  }, []);

  const handleSelectLayer = useCallback((layer: LayerId) => {
    setSelectedLayer(prev => prev === layer ? null : layer);
  }, []);

  return (
    <div className="min-h-screen bg-gray-100">
      {/* 顶部导航栏 */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-[1600px] mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-orange-500 to-amber-500 rounded-xl flex items-center justify-center shadow-lg">
                <Cpu className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-gray-900 leading-tight">
                  {t('app.title')}
                  <span className="ml-2 text-xs font-mono text-orange-500 bg-orange-50 px-2 py-0.5 rounded">
                    {version}
                  </span>
                </h1>
                <p className="text-[10px] text-gray-500">{t('app.subtitle')}</p>
              </div>
            </div>
            
            {/* 状态指示器 */}
            <div className="flex items-center gap-4">
              <RequirementsImporter />
              <ImportTaskImporter />
              <Link to="/mahjong">
                <Button variant="ghost" size="sm" className="text-xs">
                  <Gamepad2 className="w-3.5 h-3.5 mr-1" /> {t('nav.mahjong')}
                </Button>
              </Link>
              <LanguageSwitcher />
              <div className="flex items-center gap-1.5 text-xs text-gray-600">
                <Radio className="w-3.5 h-3.5 text-green-500 animate-pulse" />
                <span>{t('app.status.running')}</span>
              </div>
              <div className="h-4 w-px bg-gray-300" />
              <div className="text-xs text-gray-500">
                {t('app.metrics.throughput')}: <span className="font-mono font-bold text-gray-800">{data.systemState.throughput}</span> {t('app.metrics.tpm')}
              </div>
              <div className="h-4 w-px bg-gray-300" />
              <div className="text-xs text-gray-500">
                {t('app.metrics.latency')}: <span className="font-mono font-bold text-gray-800">{formatDuration(data.systemState.avgLatency, 'compact')}</span>
              </div>
              <div className="h-4 w-px bg-gray-300" />
              <div className="text-xs text-gray-500">
                {t('app.metrics.tasks')}: <span className="font-mono font-bold text-gray-800">{data.systemState.activeTasks}</span> {t('app.metrics.active')}
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* 主内容区域 */}
      <main className="max-w-[1600px] mx-auto px-4 py-4">
        <div className="grid grid-cols-12 gap-4">
          
          {/* 左侧：架构可视化 */}
          <div className="col-span-12 lg:col-span-3">
            <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
              <LayerVisualizer 
                data={data} 
                selectedLayer={selectedLayer}
                onSelectLayer={handleSelectLayer}
              />
              
              {/* 选中层的详细信息 */}
              {selectedLayer && (
                <div className="mt-4 p-3 bg-orange-50 rounded-lg border border-orange-200">
                  <h4 className="text-sm font-bold text-orange-800 mb-2">
                    {selectedLayer} {t('layer.title')}
                  </h4>
                  {(() => {
                    const layerDef = data.layerMetrics.find(l => l.layerId === selectedLayer);
                    return layerDef ? (
                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span className="text-gray-600">{t('layer.tasksProcessed')}</span>
                          <span className="font-mono font-bold">{layerDef.tasksProcessed}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-600">{t('layer.avgLatency')}</span>
                          <span className="font-mono font-bold">{formatDuration(layerDef.avgLatency, 'compact')}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-600">{t('layer.successRate')}</span>
                          <span className="font-mono font-bold">{NumberPrecision.percentage(layerDef.successRate)}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-600">{t('layer.engineUtilization')}</span>
                          <span className="font-mono font-bold">{NumberPrecision.percentage(layerDef.engineUtilization)}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-600">{t('layer.activeEngines')}</span>
                          <span className="font-mono font-bold">{layerDef.activeEngines}</span>
                        </div>
                      </div>
                    ) : null;
                  })()}
                </div>
              )}
            </div>
          </div>

          {/* 右侧：标签页内容 */}
          <div className="col-span-12 lg:col-span-9">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
              <TabsList className="w-full grid grid-cols-6 mb-4 bg-white border border-gray-200 p-1 rounded-xl">
                <TabsTrigger value="overview" className="text-xs rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white">
                  <BarChart3 className="w-3.5 h-3.5 mr-1" /> {t('nav.overview')}
                </TabsTrigger>
                <TabsTrigger value="tasks" className="text-xs rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white">
                  <Terminal className="w-3.5 h-3.5 mr-1" /> {t('nav.tasks')}
                </TabsTrigger>
                <TabsTrigger value="outputs" className="text-xs rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white">
                  <FolderOpen className="w-3.5 h-3.5 mr-1" />产出物
                </TabsTrigger>
                <TabsTrigger value="evolution" className="text-xs rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white">
                  <GitBranch className="w-3.5 h-3.5 mr-1" /> {t('nav.evolution')}
                </TabsTrigger>
                <TabsTrigger value="safety" className="text-xs rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white">
                  <ShieldCheck className="w-3.5 h-3.5 mr-1" /> {t('nav.safety')}
                </TabsTrigger>
                <TabsTrigger value="memory" className="text-xs rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white">
                  <Brain className="w-3.5 h-3.5 mr-1" /> {t('nav.memory')}
                </TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="mt-0">
                <SystemDashboard data={data} />
              </TabsContent>

              <TabsContent value="tasks" className="mt-0">
                <TaskPanel />
              </TabsContent>

              <TabsContent value="outputs" className="mt-0">
                <ProjectOutputReview />
              </TabsContent>

              <TabsContent value="evolution" className="mt-0">
                <EvolutionBrowser data={data} />
              </TabsContent>

              <TabsContent value="safety" className="mt-0">
                <SafetyPanel data={data} />
              </TabsContent>

              <TabsContent value="memory" className="mt-0">
                <MemoryPanel data={data} />
              </TabsContent>
            </Tabs>
          </div>
        </div>

        {/* 底部信息栏 */}
        <footer className="mt-6 text-center text-[10px] text-gray-400 pb-4">
          <p>{t('app.title')} <span className="font-mono text-orange-500">{version}</span> — {t('app.subtitle')} | {t('footer.architecture')}</p>
          <p className="mt-0.5">{t('footer.integrations')}</p>
        </footer>
      </main>
    </div>
  );
}
