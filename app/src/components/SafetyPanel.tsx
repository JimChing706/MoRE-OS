import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { AuditLogEntry, DashboardData, SafetyEvent } from '@/types/morev3';
import { ShieldAlert, ShieldCheck, AlertTriangle, AlertCircle, Info, Clock, CheckCircle2, FileText, Users, Scale } from 'lucide-react';
import { formatTimestamp } from '@/lib/format';
import { useTranslation } from 'react-i18next';

interface SafetyPanelProps {
  data: DashboardData;
}

const severityConfig = {
  critical: { color: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200', icon: <ShieldAlert className="w-4 h-4" /> },
  high: { color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200', icon: <AlertTriangle className="w-4 h-4" /> },
  medium: { color: 'text-yellow-600', bg: 'bg-yellow-50', border: 'border-yellow-200', icon: <AlertCircle className="w-4 h-4" /> },
  low: { color: 'text-blue-600', bg: 'bg-blue-50', border: 'border-blue-200', icon: <Info className="w-4 h-4" /> },
};

const typeLabels: Record<SafetyEvent['type'], string> = {
  sandbox_breach: '沙箱逃逸',
  ontology_violation: '本体违规',
  self_modification: '自我修改',
  unauthorized_access: '未授权访问',
};

export function SafetyPanel({ data }: SafetyPanelProps) {
  const { safetyEvents, systemState } = data;
  const unresolved = safetyEvents.filter(e => !e.resolved);
  const resolved = safetyEvents.filter(e => e.resolved);

  const severityCount = {
    critical: safetyEvents.filter(e => e.severity === 'critical').length,
    high: safetyEvents.filter(e => e.severity === 'high').length,
    medium: safetyEvents.filter(e => e.severity === 'medium').length,
    low: safetyEvents.filter(e => e.severity === 'low').length,
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
        <ShieldCheck className="w-5 h-5 text-red-600" />
        安全治理中心
      </h3>

      {/* 严重级别统计 */}
      <div className="grid grid-cols-4 gap-2">
        {(Object.keys(severityCount) as Array<keyof typeof severityCount>).map(severity => {
          const config = severityConfig[severity];
          return (
            <div key={severity} className={`${config.bg} ${config.border} border rounded-lg p-2 text-center`}>
              <div className={`${config.color} flex justify-center mb-1`}>{config.icon}</div>
              <p className="text-lg font-bold">{severityCount[severity]}</p>
              <p className="text-[10px] text-gray-500 capitalize">{severity}</p>
            </div>
          );
        })}
      </div>

      {/* 本体约束状态 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-blue-500" />
            AOW 本体约束
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {systemState.ontologyConstraints.map((constraint, i) => (
              <div key={i} className="flex items-center justify-between p-2 bg-gray-50 rounded">
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${constraint.enforced ? 'bg-green-500' : 'bg-red-500'}`} />
                  <div>
                    <span className="text-xs font-medium">{constraint.entity}</span>
                    <p className="text-[10px] text-gray-500">{constraint.rule}</p>
                  </div>
                </div>
                <Badge variant={constraint.enforced ? 'default' : 'destructive'} className="text-[10px]">
                  P{constraint.priority}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 安全事件列表 */}
      <div className="space-y-3">
        {unresolved.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-red-600 mb-2 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              待处理事件 ({unresolved.length})
            </h4>
            <ScrollArea className="h-48">
              <div className="space-y-2">
                {unresolved.map(event => (
                  <EventCard key={event.id} event={event} />
                ))}
              </div>
            </ScrollArea>
          </div>
        )}

        {resolved.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-green-600 mb-2 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              已解决 ({resolved.length})
            </h4>
            <ScrollArea className="h-32">
              <div className="space-y-2">
                {resolved.map(event => (
                  <EventCard key={event.id} event={event} />
                ))}
              </div>
            </ScrollArea>
          </div>
        )}

        {resolved.length === 0 && unresolved.length === 0 && (
          <div className="text-center py-8 text-gray-400">
            <ShieldCheck className="w-8 h-8 mx-auto mb-2" />
            <p className="text-sm">暂无安全事件</p>
          </div>
        )}
      </div>

      <Tabs defaultValue="audit" className="mt-4">
        <TabsList className="grid w-full grid-cols-3 h-8">
          <TabsTrigger value="audit" className="text-xs gap-1">
            <FileText className="w-3 h-3" /> 审计日志
          </TabsTrigger>
          <TabsTrigger value="rbac" className="text-xs gap-1">
            <Users className="w-3 h-3" /> RBAC
          </TabsTrigger>
          <TabsTrigger value="policy" className="text-xs gap-1">
            <Scale className="w-3 h-3" /> 策略
          </TabsTrigger>
        </TabsList>

        <TabsContent value="audit" className="mt-3">
          <AuditLogPanel auditLogs={data.auditLogs} />
        </TabsContent>

        <TabsContent value="rbac" className="mt-3">
          <RBACPanel />
        </TabsContent>

        <TabsContent value="policy" className="mt-3">
          <PolicyPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function AuditLogPanel({ auditLogs }: { auditLogs: AuditLogEntry[] }) {
  const { t } = useTranslation();

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <FileText className="w-4 h-4 text-blue-500" />
          审计日志 (AOW兼容)
        </CardTitle>
      </CardHeader>
      <CardContent>
        {auditLogs.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <FileText className="w-8 h-8 mx-auto mb-2" />
            <p className="text-sm">{t('safety.noAuditLogs')}</p>
          </div>
        ) : (
          <ScrollArea className="h-48">
            <div className="space-y-2">
              {auditLogs.map(log => (
                <div key={log.id} className="flex items-start gap-3 p-2 bg-gray-50 rounded text-xs">
                  <div className="w-16 text-gray-400 font-mono flex-shrink-0">
                    {formatTimestamp(log.timestamp)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[8px] h-4">{log.actor}</Badge>
                      <span className="text-blue-600">{log.action}</span>
                      <span className="text-gray-600 truncate">{log.entity}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

function RBACPanel() {
  const roles = [
    { name: 'admin', description: '完全系统访问权限', users: 1, permissions: 15 },
    { name: 'operator', description: '操作权限（执行任务、管理工具）', users: 2, permissions: 9 },
    { name: 'developer', description: '开发权限（代码、插件）', users: 1, permissions: 6 },
    { name: 'user', description: '普通用户权限', users: 3, permissions: 4 },
  ];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Users className="w-4 h-4 text-purple-500" />
          角色权限管理
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {roles.map(role => (
            <div key={role.name} className="flex items-center justify-between p-2 bg-gray-50 rounded">
              <div className="flex items-center gap-3">
                <div className="w-20 font-medium text-sm capitalize">{role.name}</div>
                <div className="text-[10px] text-gray-500 max-w-[120px] truncate">{role.description}</div>
              </div>
              <div className="flex items-center gap-3 text-[10px] text-gray-400">
                <span>{role.users} 用户</span>
                <span>{role.permissions} 权限</span>
                <Badge variant="outline" className="text-[8px] h-4">查看</Badge>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function PolicyPanel() {
  const policies = [
    { id: 'POL-001', name: '元认知启用检查', status: 'active', description: '检查allow_self_improvement配置与enable_metacognition一致性' },
    { id: 'POL-002', name: '超时验证', status: 'active', description: '验证任务timeout_s在有效范围(1-600秒)' },
    { id: 'POL-003', name: '安全文件白名单', status: 'active', description: '自动批准低风险文件修改' },
    { id: 'POL-004', name: '审批工作流', status: 'active', description: '高风险操作需要人工审批' },
  ];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Scale className="w-4 h-4 text-green-500" />
          策略执行状态
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {policies.map(policy => (
            <div key={policy.id} className="flex items-start gap-3 p-2 bg-gray-50 rounded">
              <div className={`w-2 h-2 rounded-full mt-1 ${policy.status === 'active' ? 'bg-green-500' : 'bg-gray-400'}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium">{policy.name}</span>
                  <Badge className="text-[8px] h-4 bg-green-500">{policy.status}</Badge>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5">{policy.description}</p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function EventCard({ event }: { event: SafetyEvent }) {
  const config = severityConfig[event.severity];
  return (
    <div className={`${config.bg} ${config.border} border rounded-lg p-2.5`}>
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-2">
          <div className={`${config.color} mt-0.5`}>{config.icon}</div>
          <div>
            <div className="flex items-center gap-1">
              <span className="text-xs font-medium">{typeLabels[event.type]}</span>
              <Badge className={`text-[8px] h-4 ${
                event.severity === 'critical' ? 'bg-red-500' :
                event.severity === 'high' ? 'bg-orange-500' :
                event.severity === 'medium' ? 'bg-yellow-500' : 'bg-blue-500'
              }`}>
                {event.severity}
              </Badge>
            </div>
            <p className="text-[10px] text-gray-600 mt-0.5">{event.description}</p>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="outline" className="text-[8px] h-4">{event.layer}</Badge>
              <span className="text-[9px] text-gray-400 flex items-center gap-0.5">
                <Clock className="w-2.5 h-2.5" />
                {formatTimestamp(event.timestamp)}
              </span>
            </div>
          </div>
        </div>
        {event.resolved && <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0" />}
      </div>
    </div>
  );
}
