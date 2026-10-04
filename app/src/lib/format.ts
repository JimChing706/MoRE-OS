export const NumberPrecision = {
  percentage: (n: number) => (n * 100).toFixed(1),
  latency: (n: number) => `${Math.round(n).toFixed(0)}ms`,
  throughput: (n: number) => `${n.toFixed(0)}/min`,
  score: (n: number) => (n * 100).toFixed(1),
  duration: (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(2)}s`;
    return `${n.toFixed(0)}ms`;
  },
  durationCompact: (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}s`;
    if (n >= 100) return `${Math.round(n / 100) / 10}K`;
    return `${Math.round(n).toFixed(0)}ms`;
  },
  ratio: (n: number) => `${(n * 100).toFixed(1)}%`,
  count: (n: number) => n.toFixed(0),
  decimal: (n: number, decimals = 2) => n.toFixed(decimals),
  tokens: (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return n.toFixed(0);
  },
};

export function formatDuration(duration: number, style: 'full' | 'compact' | 'badge' = 'full'): string {
  if (duration < 0) return '-';
  if (style === 'badge') {
    if (duration >= 1000) return `${(duration / 1000).toFixed(1)}s`;
    return `${duration}ms`;
  }
  if (style === 'compact') {
    if (duration >= 1000) return `${(duration / 1000).toFixed(1)}s`;
    return `${duration}ms`;
  }
  return `${duration.toFixed(0)}ms`;
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return tokens.toFixed(0);
}

export function formatTimestamp(ts: number, format: 'time' | 'date' | 'datetime' = 'time'): string {
  const date = new Date(ts);
  if (format === 'time') return date.toLocaleTimeString();
  if (format === 'date') return date.toLocaleDateString();
  return date.toLocaleString();
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

export const COLORS = {
  layer: {
    L0: '#FFD54F',
    L1: '#FFC107',
    L2: '#FFB300',
    L3: '#FFA000',
    L4: '#FF8F00',
    L5: '#FF6F00',
  },
  severity: {
    critical: 'bg-red-500',
    high: 'bg-orange-500',
    medium: 'bg-yellow-500',
    low: 'bg-blue-500',
  },
  status: {
    running: 'bg-green-500',
    idle: 'bg-gray-400',
    paused: 'bg-yellow-500',
    error: 'bg-red-500',
    evolving: 'bg-purple-500',
  },
  capacity: {
    safe: 'bg-green-500',
    warning: 'bg-yellow-500',
    danger: 'bg-red-500',
  },
} as const;