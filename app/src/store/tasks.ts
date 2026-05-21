import { create } from 'zustand'

export interface Task {
  task_id: string
  type: string
  query: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  output: string
  reasoning_chain: Array<{
    id: number
    layer: string
    description: string
    duration: number
    confidence: number
  }>
  performance: {
    total_duration: number
    tokens_used: number
  }
  created_at: number
  completed_at?: number
}

interface TaskState {
  tasks: Task[]
  activeTask: Task | null
  isLoading: boolean
  error: string | null

  // Actions
  addTask: (task: Task) => void
  updateTask: (taskId: string, updates: Partial<Task>) => void
  setActiveTask: (task: Task | null) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  clearTasks: () => void
  executeTask: (query: string, type?: string) => Promise<void>
}

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001'

export const useTaskStore = create<TaskState>((set, get) => ({
  tasks: [],
  activeTask: null,
  isLoading: false,
  error: null,

  addTask: (task) => set((state) => ({ tasks: [task, ...state.tasks] })),
  updateTask: (taskId, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) => (t.task_id === taskId ? { ...t, ...updates } : t)),
      activeTask:
        state.activeTask?.task_id === taskId ? { ...state.activeTask, ...updates } : state.activeTask,
    })),
  setActiveTask: (task) => set({ activeTask: task }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  clearTasks: () => set({ tasks: [] }),

  executeTask: async (query: string, type = 'nlp_task') => {
    set({ isLoading: true, error: null })
    try {
      const response = await fetch(`${API_BASE}/api/tasks/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, query }),
      })

      if (!response.ok) {
        throw new Error(`API Error: ${response.status}`)
      }

      const result = await response.json()
      const task: Task = {
        task_id: result.task_id,
        type,
        query,
        status: result.status || 'completed',
        output: result.output || '',
        reasoning_chain: result.reasoning_chain || [],
        performance: result.performance || { total_duration: 0, tokens_used: 0 },
        created_at: Date.now(),
      }

      set((state) => ({
        tasks: [task, ...state.tasks].slice(0, 100),
        activeTask: task,
        isLoading: false,
      }))
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Unknown error',
        isLoading: false,
      })
    }
  },
}))
