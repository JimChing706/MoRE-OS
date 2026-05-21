import { useState, useEffect } from 'react';
import type { LayerDefinition, LayerId, DashboardData } from '@/types/morev3';
import { getLayerDefinitions } from '@/core/moreEngine';
import { Activity, Brain, Cpu, GitBranch, Network, Shield, Zap, Server } from 'lucide-react';
import { formatDuration } from '@/lib/format';
import { NumberPrecision } from '@/lib/format';

const layerIcons: Record<LayerId, React.ReactNode> = {
  L5: <Brain className="w-6 h-6" />,
  L4: <Zap className="w-6 h-6" />,
  L3: <Shield className="w-6 h-6" />,
  L2: <GitBranch className="w-6 h-6" />,
  L1: <Network className="w-6 h-6" />,
  L0: <Server className="w-6 h-6" />,
};

interface LayerVisualizerProps {
  data?: DashboardData;
  selectedLayer: LayerId | null;
  onSelectLayer: (layer: LayerId) => void;
}

export function LayerVisualizer({ data, selectedLayer, onSelectLayer }: LayerVisualizerProps) {
  const [layers] = useState<LayerDefinition[]>(getLayerDefinitions());
  const [animatedLayers, setAnimatedLayers] = useState<Set<LayerId>>(new Set());

  useEffect(() => {
    if (data) {
      const active = new Set<LayerId>();
      data.recentTasks.forEach(task => {
        task.reasoningChain.forEach(step => active.add(step.layer));
      });
      setAnimatedLayers(active);
    }
  }, [data]);

  const getMetricForLayer = (layerId: LayerId) => {
    if (!data) return null;
    return data.layerMetrics.find(m => m.layerId === layerId);
  };

  return (
    <div className="space-y-2">
      <h3 className="text-lg font-bold text-gray-800 mb-3 flex items-center gap-2">
        <Cpu className="w-5 h-5 text-orange-600" />
        MoRE v3.0 六层架构
      </h3>
      {[...layers].reverse().map((layer) => {
        const metric = getMetricForLayer(layer.id);
        const isActive = animatedLayers.has(layer.id);
        const isSelected = selectedLayer === layer.id;
        return (
          <div
            key={layer.id}
            onClick={() => onSelectLayer(layer.id)}
            className={`
              relative rounded-lg border-2 cursor-pointer transition-all duration-300
              ${isSelected ? 'border-orange-500 shadow-lg shadow-orange-100' : 'border-gray-200 hover:border-orange-300'}
              ${isActive ? 'ring-2 ring-orange-300 ring-opacity-60' : ''}
            `}
            style={{ 
              backgroundColor: `${layer.color}15`,
            }}
          >
            {/* 活跃流动动画 */}
            {isActive && (
              <div 
                className="absolute inset-0 rounded-lg animate-pulse"
                style={{ backgroundColor: `${layer.color}20` }}
              />
            )}
            
            <div className="relative p-3 flex items-center gap-3">
              {/* 层级指示 */}
              <div 
                className="flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold"
                style={{ backgroundColor: layer.color }}
              >
                {layerIcons[layer.id]}
              </div>

              {/* 内容 */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-gray-500">{layer.id}</span>
                  <span className="font-bold text-gray-800 text-sm">{layer.name}</span>
                  <span className="text-xs text-gray-400">{layer.englishName}</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5 truncate">{layer.description}</p>
                
                {/* 引擎状态 */}
                <div className="flex gap-1 mt-1.5">
                  {layer.engines.map(engine => (
                    <span
                      key={engine.id}
                      className={`
                        inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium
                        ${engine.status === 'running' ? 'bg-green-100 text-green-700' : ''}
                        ${engine.status === 'idle' ? 'bg-gray-100 text-gray-600' : ''}
                        ${engine.status === 'evolving' ? 'bg-purple-100 text-purple-700 animate-pulse' : ''}
                      `}
                    >
                      <Activity className="w-2.5 h-2.5 mr-0.5" />
                      {engine.name.split('引擎')[0]}
                    </span>
                  ))}
                </div>
              </div>

              {/* 指标 */}
              {metric && (
                <div className="flex-shrink-0 text-right space-y-0.5">
                  <div className="text-xs text-gray-500">
                    {formatDuration(metric.avgLatency, 'compact')}
                  </div>
                  <div className="text-xs font-medium" style={{ color: layer.color }}>
                    {NumberPrecision.percentage(metric.successRate)}%
                  </div>
                  {/* 负载条 */}
                  <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                    <div 
                      className="h-full rounded-full transition-all duration-500"
                      style={{ 
                        width: `${metric.engineUtilization * 100}%`,
                        backgroundColor: layer.color,
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
