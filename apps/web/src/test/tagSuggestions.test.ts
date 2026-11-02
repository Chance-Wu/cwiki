import { describe, it, expect } from 'vitest'
import { suggestTagMerges } from '../lib/tagSuggestions'

describe('suggestTagMerges', () => {
  it('suggests merging case variants and keeps the most used spelling', () => {
    const result = suggestTagMerges([
      { name: 'React', count: 2 },
      { name: 'react', count: 5 },
    ])
    expect(result).toHaveLength(1)
    expect(result[0].reason).toBe('case')
    expect(result[0].target).toBe('react')
    expect(result[0].tags).toEqual(expect.arrayContaining(['React', 'react']))
  })

  it('detects spacing differences', () => {
    const result = suggestTagMerges([
      { name: 'react', count: 3 },
      { name: ' react ', count: 1 },
    ])
    expect(result).toHaveLength(1)
    expect(result[0].reason).toBe('spacing')
  })

  it('detects plural variants for latin tags', () => {
    const result = suggestTagMerges([
      { name: 'react', count: 3 },
      { name: 'reacts', count: 1 },
    ])
    expect(result).toHaveLength(1)
    expect(result[0].reason).toBe('plural')
    expect(result[0].target).toBe('react')
  })

  it('does not merge unrelated tags', () => {
    expect(
      suggestTagMerges([
        { name: 'java', count: 2 },
        { name: 'javascript', count: 2 },
      ]),
    ).toHaveLength(0)
  })

  it('ignores unique tags', () => {
    expect(suggestTagMerges([{ name: 'redis', count: 1 }])).toHaveLength(0)
  })
})
