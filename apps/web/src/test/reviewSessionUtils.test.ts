import { describe, it, expect } from 'vitest'
import {
  clampGoal,
  formatClock,
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
