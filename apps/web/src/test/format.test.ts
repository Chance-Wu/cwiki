import { describe, it, expect } from 'vitest'
import { formatTime, formatTimeShort, formatRelativeTime } from '../lib/format'

describe('format utilities', () => {
  describe('formatTime', () => {
    it('returns dash for null input', () => {
      expect(formatTime(null, 'en')).toBe('-')
    })

    it('formats date in English locale', () => {
      const result = formatTime('2026-09-15T10:30:00Z', 'en')
      expect(result).toMatch(/09\/15\/2026/)
    })

    it('formats date in Chinese locale', () => {
      const result = formatTime('2026-09-15T10:30:00Z', 'zh')
      expect(result).toMatch(/2026\/09\/15/)
    })
  })

  describe('formatTimeShort', () => {
    it('returns dash for null input', () => {
      expect(formatTimeShort(null, 'en')).toBe('-')
    })

    it('formats date without year', () => {
      const result = formatTimeShort('2026-09-15T10:30:00Z', 'en')
      expect(result).toMatch(/09\/15/)
      expect(result).not.toMatch(/2026/)
    })
  })

  describe('formatRelativeTime', () => {
    const strings = {
      justNow: 'just now',
      minutesAgo: '{n} minutes ago',
      hoursAgo: '{n} hours ago',
      daysAgo: '{n} days ago',
    }

    it('returns just now for recent times', () => {
      const now = new Date().toISOString()
      expect(formatRelativeTime(now, strings, 'en')).toBe('just now')
    })

    it('returns minutes ago', () => {
      const fiveMinAgo = new Date(Date.now() - 5 * 60000).toISOString()
      expect(formatRelativeTime(fiveMinAgo, strings, 'en')).toBe('5 minutes ago')
    })

    it('returns hours ago', () => {
      const twoHoursAgo = new Date(Date.now() - 2 * 3600000).toISOString()
      expect(formatRelativeTime(twoHoursAgo, strings, 'en')).toBe('2 hours ago')
    })

    it('returns days ago', () => {
      const threeDaysAgo = new Date(Date.now() - 3 * 86400000).toISOString()
      expect(formatRelativeTime(threeDaysAgo, strings, 'en')).toBe('3 days ago')
    })
  })
})
