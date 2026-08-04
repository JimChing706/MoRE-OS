import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SafetyPanel } from './SafetyPanel'
import type { DashboardData } from '@/types/morev3'

const mocks = vi.hoisted(() => {
  return {
    t: (key: string) => (key === 'safety.noAuditLogs' ? 'no audit logs available' : key),
  }
})

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mocks.t }),
}))

class ResizeObserverMock {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const baseData: DashboardData = {
  systemState: {
    status: 'running',
    activeLayers: ['L0'],
    engineStatuses: { L0: [], L1: [], L2: [], L3: [], L4: [], L5: [] },
    throughput: 0,
    avgLatency: 0,
    errorRate: 0,
    activeTasks: 0,
    queuedTasks: 0,
    evolutionArchive: { agents: [], branches: [], currentBest: '', archiveSize: 0, maxArchiveSize: 0 },
    ontologyConstraints: [],
  },
  recentTasks: [],
  memorySystem: { episodic: [], semantic: [], procedural: [] },
  safetyEvents: [],
  auditLogs: [],
  layerMetrics: [],
  evolutionStats: {
    totalAgents: 0,
    totalBranches: 0,
    currentBestScore: 0,
    improvementRate: 0,
    activeMutations: 0,
    convergenceStatus: 'exploring',
  },
}

describe('SafetyPanel — AuditLog tab', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders audit log records', () => {
    const data: DashboardData = {
      ...baseData,
      auditLogs: [
        { id: 'audit_001', timestamp: Date.now() - 60000, actor: 'admin', action: 'execute', entity: 'task_abc123', payload: { layer: 'L3', status: 'success' } },
        { id: 'audit_002', timestamp: Date.now() - 120000, actor: 'system', action: 'evolve', entity: 'agent_xyz', payload: { branch: 'main' } },
      ],
    }
    render(<SafetyPanel data={data} />)

    expect(screen.getByText('admin')).toBeInTheDocument()
    expect(screen.getByText('execute')).toBeInTheDocument()
    expect(screen.getByText('system')).toBeInTheDocument()
    expect(screen.getByText('evolve')).toBeInTheDocument()
    expect(screen.getByText('task_abc123')).toBeInTheDocument()
  })

  it('shows an empty state when there are no audit logs', () => {
    render(<SafetyPanel data={baseData} />)

    expect(screen.getByText('no audit logs available')).toBeInTheDocument()
  })
})
