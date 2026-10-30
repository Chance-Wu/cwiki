import { describe, it, expect } from 'vitest'
import zh from '../i18n/locales/zh'
import { typeLabel, TYPE_COLORS, TYPE_HEX } from '../lib/labels'

// 与后端 packages/domain/types.py 的 ALL_TYPES 保持一致
const ALL_TYPES = [
  'fact',
  'decision',
  'issue',
  'convention',
  'pattern',
  'procedure',
  'feedback',
  'reference',
  'constraint',
  'lesson',
  'rule',
] as const

describe('memory type labels', () => {
  it('maps every type to a translated label (not the raw key)', () => {
    for (const type of ALL_TYPES) {
      expect(typeLabel(zh.common, type)).not.toBe(type)
    }
  })

  it('has a color for every type', () => {
    for (const type of ALL_TYPES) {
      expect(TYPE_COLORS[type], `missing color for "${type}"`).toBeTruthy()
    }
  })

  it('has a canvas hex color for every type', () => {
    for (const type of ALL_TYPES) {
      expect(TYPE_HEX[type], `missing hex for "${type}"`).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
})
