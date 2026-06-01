/**
 * 任务记忆积累系统 — useTaskMemory Hook
 *
 * 将每次任务执行结果存储在 localStorage 中，按类型分组。
 * 提交新任务时自动注入相关历史上下文，实现:
 *   - 同类型任务的解决方案积累
 *   - 模式识别与经验复用
 *   - 记忆统计与可视化
 *
 * 对应后端 MemoryStore (memory.db) 的前端记忆层。
 */

import { useState, useCallback, useMemo } from 'react';
import type { TaskType, TaskResult } from '@/types/morev3';

const STORAGE_KEY = 'more_os_task_memory';
const MAX_MEMORIES_PER_TYPE = 20;
const MAX_CONTEXT_LENGTH = 2000;

export interface TaskMemory {
  id: string;
  type: TaskType;
  query: string;
  output: string;
  status: string;
  layer: string;
  duration_ms: number;
  timestamp: number;
}

interface MemoryStats {
  totalMemories: number;
  byType: Record<string, number>;
  topTypes: { type: string; count: number }[];
}

function loadMemories(): TaskMemory[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveMemories(memories: TaskMemory[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(memories));
  } catch {
    // localStorage full — trim oldest
    const trimmed = memories.slice(-MAX_MEMORIES_PER_TYPE * 5);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  }
}

/** Simple keyword-overlap similarity for finding related past tasks. */
function similarityScore(query: string, memory: TaskMemory): number {
  const qWords = new Set(query.toLowerCase().split(/\s+/));
  const mWords = memory.query.toLowerCase().split(/\s+/);
  if (mWords.length === 0) return 0;
  let matches = 0;
  for (const w of mWords) {
    if (qWords.has(w)) matches++;
  }
  return matches / mWords.length;
}

export function useTaskMemory() {
  const [memories, setMemories] = useState<TaskMemory[]>(loadMemories);

  const stats: MemoryStats = useMemo(() => {
    const byType: Record<string, number> = {};
    for (const m of memories) {
      byType[m.type] = (byType[m.type] || 0) + 1;
    }
    const topTypes = Object.entries(byType)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([type, count]) => ({ type, count }));
    return { totalMemories: memories.length, byType, topTypes };
  }, [memories]);

  /** Record a completed task to memory. */
  const remember = useCallback((result: TaskResult, query: string) => {
    setMemories(prev => {
      const entry: TaskMemory = {
        id: result.taskId,
        type: result.layer as unknown as TaskType,
        query: query.slice(0, 500),
        output: result.output.slice(0, 1000),
        status: result.status,
        layer: result.layer,
        duration_ms: result.performance?.totalDuration ?? 0,
        timestamp: Date.now(),
      };
      // Keep per-type cap
      const others = prev.filter(m => m.type !== entry.type || m.id === entry.id);
      const sameType = prev.filter(m => m.type === entry.type && m.id !== entry.id);
      const updated = [...others, ...sameType.slice(-(MAX_MEMORIES_PER_TYPE - 1)), entry];
      saveMemories(updated);
      return updated;
    });
  }, []);

  /** Retrieve related past tasks for context injection. */
  const getRelatedContext = useCallback((query: string, taskType: string): string => {
    const sameType = memories.filter(m => m.type === taskType);
    if (sameType.length === 0) return '';

    // Score by similarity, take top 3
    const scored = sameType
      .map(m => ({ memory: m, score: similarityScore(query, m) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .filter(s => s.score > 0.05);

    if (scored.length === 0) return '';

    const parts = scored.map((s, i) =>
      `[Past Task ${i + 1}] Query: ${s.memory.query.slice(0, 200)}\nResult: ${s.memory.output.slice(0, 300)}`
    );
    let context = "[SYSTEM MEMORY — Related Past Tasks]\n" + parts.join('\n\n');

    // Truncate if too long
    if (context.length > MAX_CONTEXT_LENGTH) {
      context = context.slice(0, MAX_CONTEXT_LENGTH) + '\n... (truncated)';
    }
    return context;
  }, [memories]);

  /** Get memories for a specific task type. */
  const getByType = useCallback((taskType: string): TaskMemory[] => {
    return memories.filter(m => m.type === taskType).slice(-10);
  }, [memories]);

  /** Clear all memories. */
  const clearAll = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setMemories([]);
  }, []);

  return { memories, stats, remember, getRelatedContext, getByType, clearAll };
}
