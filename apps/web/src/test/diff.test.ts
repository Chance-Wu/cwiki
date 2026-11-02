import { describe, it, expect } from 'vitest'
import { computeAlignedRows } from '../lib/diff'

describe('computeAlignedRows', () => {
  it('marks identical lines as unchanged', () => {
    const rows = computeAlignedRows('alpha\nbeta', 'alpha\nbeta')
    expect(rows).toHaveLength(2)
    expect(rows.every((row) => row.left.type === 'unchanged')).toBe(true)
    expect(rows.every((row) => row.right.type === 'unchanged')).toBe(true)
  })

  it('marks added lines on the right side', () => {
    const rows = computeAlignedRows('alpha', 'alpha\nbeta')
    const added = rows.filter((row) => row.right.type === 'added')
    expect(added).toHaveLength(1)
    expect(added[0].right.content).toBe('beta')
    expect(added[0].left.type).toBe('empty')
  })

  it('marks removed lines on the left side', () => {
    const rows = computeAlignedRows('alpha\nbeta', 'alpha')
    const removed = rows.filter((row) => row.left.type === 'removed')
    expect(removed).toHaveLength(1)
    expect(removed[0].left.content).toBe('beta')
    expect(removed[0].right.type).toBe('empty')
  })

  it('pairs replaced lines', () => {
    const rows = computeAlignedRows('old line', 'new line')
    const changed = rows.filter((row) => row.left.type === 'removed' || row.right.type === 'added')
    expect(changed).toHaveLength(1)
    expect(changed[0].left.content).toBe('old line')
    expect(changed[0].right.content).toBe('new line')
  })
})
