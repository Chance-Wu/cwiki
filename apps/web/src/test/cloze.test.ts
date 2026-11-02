import { describe, it, expect } from 'vitest'
import { buildCloze } from '../lib/cloze'

describe('buildCloze', () => {
  it('masks tag terms present in content', () => {
    const result = buildCloze(
      '线程池的核心参数是 corePoolSize 与 maximumPoolSize。',
      '线程池配置',
      ['线程池'],
    )
    expect(result).not.toBeNull()
    expect(result!.text).toContain('____')
    expect(result!.terms).toContain('线程池')
  })

  it('does not mask inside fenced or inline code', () => {
    const content = '使用 Redis 做缓存，示例：\n```\nRedis 配置示例\n```\n生产环境也用 Redis。'
    const result = buildCloze(content, 'Redis 缓存', ['Redis'])
    expect(result).not.toBeNull()
    expect(result!.text).toContain('```\nRedis 配置示例\n```')
    // 每个术语只挖第一处，后续出现保持原文
    expect(result!.text).toContain('生产环境也用 Redis。')
  })

  it('respects latin word boundaries', () => {
    const result = buildCloze('Java 的 ThreadPool 与 ThreadPools 不同', 'ThreadPool', [])
    expect(result).not.toBeNull()
    expect(result!.text).toContain('____')
    expect(result!.text).toContain('ThreadPools')
  })

  it('returns null when no candidate appears in content', () => {
    expect(buildCloze('完全无关的正文', '标题', ['缺失标签'])).toBeNull()
  })

  it('limits to three terms', () => {
    const result = buildCloze('Alpha Beta Gamma Delta', '', ['Alpha', 'Beta', 'Gamma', 'Delta'])
    expect(result).not.toBeNull()
    expect(result!.terms).toHaveLength(3)
  })

  it('returns null for empty content or tags', () => {
    expect(buildCloze('', '', [])).toBeNull()
  })
})
