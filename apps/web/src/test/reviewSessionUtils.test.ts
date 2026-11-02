import { describe, it, expect } from 'vitest'
import {
  clampGoal,
  formatClock,
  normalizeIndex,
  parseReviewSession,
  rebuildQueue,
  DAILY_GOAL_DEFAULT,
  DAILY_GOAL_MIN,
  DAILY_GOAL_MAX,
} from '../components/review/reviewSessionUtils'

describe('clampGoal', () => {
  it('clamps below minimum and above maximum', () => {
    expect(clampGoal(0)).toBe(DAILY_GOAL_MIN)
    expect(clampGoal(-5)).toBe(DAILY_GOAL_MIN)
    expect(clampGoal(999)).toBe(DAILY_GOAL_MAX)
  })

  it('rounds and keeps in-range values', () => {
    expect(clampGoal(20)).toBe(20)
    expect(clampGoal(3.6)).toBe(4)
  })

  it('falls back to default for non-finite input', () => {
    expect(clampGoal(Number.NaN)).toBe(DAILY_GOAL_DEFAULT)
    expect(clampGoal(Number.POSITIVE_INFINITY)).toBe(DAILY_GOAL_MAX)
  })
})

describe('formatClock', () => {
  it('formats under an hour as mm:ss', () => {
    expect(formatClock(0)).toBe('00:00')
    expect(formatClock(65)).toBe('01:05')
    expect(formatClock(599)).toBe('09:59')
  })

  it('formats an hour or more as h:mm:ss', () => {
    expect(formatClock(3661)).toBe('1:01:01')
  })

  it('clamps negative and floors fractional seconds', () => {
    expect(formatClock(-10)).toBe('00:00')
    expect(formatClock(12.9)).toBe('00:12')
  })
})

describe('parseReviewSession', () => {
  it('returns null for empty or malformed input', () => {
    expect(parseReviewSession(null)).toBeNull()
    expect(parseReviewSession('')).toBeNull()
    expect(parseReviewSession('{bad')).toBeNull()
    expect(parseReviewSession('123')).toBeNull()
  })

  it('normalizes partial payloads', () => {
    const parsed = parseReviewSession(JSON.stringify({ queueIds: ['a', 1, 'b'], currentIndex: -3 }))
    expect(parsed).not.toBeNull()
    expect(parsed!.queueIds).toEqual(['a', 'b'])
    expect(parsed!.currentIndex).toBe(0)
    expect(parsed!.filterMastery).toBeNull()
    expect(parsed!.sessionQualities).toEqual([])
  })

  it('keeps valid fields as-is', () => {
    const parsed = parseReviewSession(
      JSON.stringify({
        queueIds: ['x'],
        currentIndex: 2,
        sessionReviewed: 2,
        sessionQualities: [4, 5],
        filterMastery: 'new',
        filterType: 'fact',
      }),
    )
    expect(parsed).toEqual({
      queueIds: ['x'],
      currentIndex: 2,
      sessionReviewed: 2,
      sessionQualities: [4, 5],
      filterMastery: 'new',
      filterType: 'fact',
    })
  })
})

describe('rebuildQueue', () => {
  const items = [
    { memory_id: 'a', title: 'A' },
    { memory_id: 'b', title: 'B' },
    { memory_id: 'c', title: 'C' },
  ]

  it('returns items unchanged when no queue ids saved', () => {
    expect(rebuildQueue(items, [])).toEqual(items)
  })

  it('keeps saved order and drops missing ids', () => {
    expect(rebuildQueue(items, ['c', 'x', 'a']).map((i) => i.memory_id)).toEqual(['c', 'a'])
  })
})

describe('normalizeIndex', () => {
  it('clamps to valid range', () => {
    expect(normalizeIndex(-1, 5)).toBe(0)
    expect(normalizeIndex(2.7, 5)).toBe(2)
    expect(normalizeIndex(9, 5)).toBe(5)
    expect(normalizeIndex(1, 0)).toBe(0)
    expect(normalizeIndex(Number.NaN, 5)).toBe(0)
  })
})
