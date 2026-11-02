import { describe, it, expect } from 'vitest'
import { resolveSearchMode } from '../hooks/useSearch'

describe('resolveSearchMode', () => {
  it('keeps explicit modes', () => {
    expect(resolveSearchMode('anything', 'text')).toBe('text')
    expect(resolveSearchMode('anything', 'semantic')).toBe('semantic')
    expect(resolveSearchMode('anything', 'hybrid')).toBe('hybrid')
  })

  it('uses text for short or quoted queries', () => {
    expect(resolveSearchMode('redis', 'auto')).toBe('text')
    expect(resolveSearchMode('"exact phrase"', 'auto')).toBe('text')
  })

  it('uses semantic for natural language questions', () => {
    expect(resolveSearchMode('如何配置线程池', 'auto')).toBe('semantic')
    expect(resolveSearchMode('what is the best approach?', 'auto')).toBe('semantic')
  })

  it('falls back to hybrid', () => {
    expect(resolveSearchMode('线程池 核心参数 调优', 'auto')).toBe('hybrid')
  })
})
