import { describe, it, expect } from 'vitest'
import { NumberPrecision, formatDuration, formatTokens, formatTimestamp, formatBytes, COLORS } from './format'

describe('NumberPrecision', () => {
  it('formats percentage correctly', () => {
    expect(NumberPrecision.percentage(0.5)).toBe('50.0')
    expect(NumberPrecision.percentage(0.123)).toBe('12.3')
  })

  it('formats latency correctly', () => {
    expect(NumberPrecision.latency(150.5)).toBe('151ms')
    expect(NumberPrecision.latency(0)).toBe('0ms')
  })

  it('formats throughput correctly', () => {
    expect(NumberPrecision.throughput(42.7)).toBe('43/min')
  })

  it('formats duration with unit conversion', () => {
    expect(NumberPrecision.duration(500)).toBe('500ms')
    expect(NumberPrecision.duration(1500)).toBe('1.50s')
  })

  it('formats duration compact', () => {
    expect(NumberPrecision.durationCompact(50)).toBe('50ms')
    expect(NumberPrecision.durationCompact(150)).toBe('0.2K')
    expect(NumberPrecision.durationCompact(1500)).toBe('1.5s')
  })

  it('formats ratio', () => {
    expect(NumberPrecision.ratio(0.75)).toBe('75.0%')
  })

  it('formats tokens with K suffix', () => {
    expect(NumberPrecision.tokens(500)).toBe('500')
    expect(NumberPrecision.tokens(1500)).toBe('1.5K')
  })
})

describe('formatDuration', () => {
  it('returns dash for negative', () => {
    expect(formatDuration(-1)).toBe('-')
  })

  it('formats in full style', () => {
    expect(formatDuration(250)).toBe('250ms')
    expect(formatDuration(250, 'full')).toBe('250ms')
  })

  it('formats in compact style', () => {
    expect(formatDuration(1500, 'compact')).toBe('1.5s')
  })

  it('formats in badge style', () => {
    expect(formatDuration(3000, 'badge')).toBe('3.0s')
    expect(formatDuration(50, 'badge')).toBe('50ms')
  })
})

describe('formatTokens', () => {
  it('formats small numbers', () => {
    expect(formatTokens(42)).toBe('42')
  })

  it('formats large numbers with K', () => {
    expect(formatTokens(1200)).toBe('1.2K')
    expect(formatTokens(10000)).toBe('10.0K')
  })
})

describe('formatTimestamp', () => {
  it('returns time string', () => {
    const result = formatTimestamp(1700000000000, 'time')
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
  })

  it('returns date string', () => {
    const result = formatTimestamp(1700000000000, 'date')
    expect(typeof result).toBe('string')
  })

  it('returns datetime string', () => {
    const result = formatTimestamp(1700000000000, 'datetime')
    expect(typeof result).toBe('string')
  })
})

describe('formatBytes', () => {
  it('handles zero', () => {
    expect(formatBytes(0)).toBe('0 B')
  })

  it('formats bytes', () => {
    expect(formatBytes(512)).toBe('512.0 B')
  })

  it('formats kilobytes', () => {
    expect(formatBytes(1024)).toBe('1.0 KB')
  })

  it('formats megabytes', () => {
    expect(formatBytes(1048576)).toBe('1.0 MB')
  })

  it('formats gigabytes', () => {
    expect(formatBytes(1073741824)).toBe('1.0 GB')
  })
})

describe('COLORS', () => {
  it('has layer colors for all layers', () => {
    for (const layer of ['L0', 'L1', 'L2', 'L3', 'L4', 'L5']) {
      expect(COLORS.layer[layer as keyof typeof COLORS.layer]).toBeDefined()
    }
  })

  it('has severity colors', () => {
    expect(COLORS.severity.critical).toBe('bg-red-500')
    expect(COLORS.severity.high).toBe('bg-orange-500')
  })

  it('has status colors', () => {
    expect(COLORS.status.running).toBe('bg-green-500')
    expect(COLORS.status.error).toBe('bg-red-500')
  })
})
