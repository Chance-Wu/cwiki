import type { TranslationKeys } from '../i18n/locales/en'

type Common = TranslationKeys['common']

export function typeLabel(t: Common, type: string): string {
  const map: Record<string, string> = {
    fact: t.typeFact,
    decision: t.typeDecision,
    issue: t.typeIssue,
    convention: t.typeConvention,
    pattern: t.typePattern,
    procedure: t.typeProcedure,
    feedback: t.typeFeedback,
    reference: t.typeReference,
    constraint: t.typeConstraint,
    lesson: t.typeLesson,
    rule: t.typeRule,
  }
  return map[type] || type
}

export const MEMORY_STATUSES = ['active', 'superseded', 'conflicted', 'deprecated'] as const

export function memoryStatusLabel(
  t: TranslationKeys['memories'],
  status: string | null | undefined,
): string {
  const map: Record<string, string> = {
    active: t.statusActive,
    superseded: t.statusSuperseded,
    conflicted: t.statusConflicted,
    deprecated: t.statusDeprecated,
  }
  return map[status || 'active'] || status || t.statusActive
}

export function memoryStatusVariant(
  status: string | null | undefined,
): 'success' | 'warning' | 'danger' {
  if (status === 'deprecated') return 'warning'
  if (status === 'superseded' || status === 'conflicted') return 'danger'
  return 'success'
}

export function sourceLabel(t: Common, source: string): string {
  const map: Record<string, string> = {
    mcp: t.sourceMcp,
    worker: t.sourceWorker,
  }
  return map[source] || source
}

export function conflictTypeLabel(t: Common, type: string): string {
  const map: Record<string, string> = {
    contradiction: t.conflictContradiction,
    similarity: t.conflictSimilarity,
  }
  return map[type] || type
}

export const TYPE_COLORS: Record<string, string> = {
  fact: 'bg-info/22 border-info/35 text-info-fg',
  decision: 'bg-brand-200/45 border-brand-300/40 text-brand-fg',
  issue: 'bg-danger/22 border-danger/35 text-danger-fg',
  convention: 'bg-info/22 border-info/35 text-info-fg',
  pattern: 'bg-success/22 border-success/35 text-success-fg',
  procedure: 'bg-success/22 border-success/35 text-success-fg',
  feedback: 'bg-brand-200/40 border-brand-300/35 text-brand-fg',
  reference: 'bg-info/15 border-info/35 text-info-fg',
  constraint: 'bg-warning/22 border-warning/35 text-warning-fg',
  lesson: 'bg-info/22 border-info/35 text-info-fg',
  rule: 'bg-brand-200/45 border-brand-300/40 text-brand-fg',
}

export const SOURCE_COLORS: Record<string, string> = {
  mcp: 'bg-info/22 border-info/35 text-info-fg',
  worker: 'bg-warning/22 border-warning/35 text-warning-fg',
}

// Canvas 用的十六进制类型色（与 TYPE_COLORS 覆盖同一组类型）
export const TYPE_HEX: Record<string, string> = {
  fact: '#3b82f6',
  decision: '#8b5cf6',
  issue: '#ef4444',
  convention: '#14b8a6',
  pattern: '#22c55e',
  procedure: '#06b6d4',
  feedback: '#ec4899',
  reference: '#0ea5e9',
  constraint: '#f97316',
  lesson: '#f59e0b',
  rule: '#a855f7',
}

export const MASTERY_COLORS: Record<string, string> = {
  new: 'bg-surface-elevated/50 text-[var(--text-secondary)] border border-[var(--border-default)]',
  learning: 'bg-danger/22 text-danger-fg border border-danger/35',
  familiar: 'bg-warning/22 text-warning-fg border border-warning/35',
  proficient: 'bg-info/22 text-info-fg border border-info/35',
  mastered: 'bg-success/22 text-success-fg border border-success/35',
}
