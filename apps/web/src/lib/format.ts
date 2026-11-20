export function ensureUtc(iso: string): string {
  if (!iso) return iso
  return iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z'
}

export function formatTime(iso: string | null, locale: string): string {
  if (!iso) return '-'
  return new Date(ensureUtc(iso)).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatTimeShort(iso: string | null, locale: string): string {
  if (!iso) return '-'
  return new Date(ensureUtc(iso)).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

interface RelativeTimeStrings {
  justNow: string
  minutesAgo: string
  hoursAgo: string
  daysAgo: string
}

export function formatRelativeTime(
  iso: string,
  strings: RelativeTimeStrings,
  locale: string,
): string {
  const date = new Date(ensureUtc(iso))
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const minutes = Math.floor(diffMs / 60000)
  const hours = Math.floor(diffMs / 3600000)
  const days = Math.floor(diffMs / 86400000)

  if (minutes < 1) return strings.justNow
  if (minutes < 60) return strings.minutesAgo.replace('{n}', String(minutes))
  if (hours < 24) return strings.hoursAgo.replace('{n}', String(hours))
  if (days < 7) return strings.daysAgo.replace('{n}', String(days))
  return date.toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US')
}

export type Freshness = 'fresh' | 'aging' | 'stale'

// 按类型的时效阈值（天）：规则/决策类记忆比事实类"保质期"更长
const FRESHNESS_THRESHOLDS: Record<string, { fresh: number; aging: number }> = {
  fact: { fresh: 30, aging: 90 },
  reference: { fresh: 30, aging: 90 },
  decision: { fresh: 60, aging: 180 },
  convention: { fresh: 60, aging: 180 },
  pattern: { fresh: 60, aging: 180 },
  issue: { fresh: 30, aging: 90 },
  procedure: { fresh: 30, aging: 90 },
  feedback: { fresh: 30, aging: 90 },
}

/** 记忆新鲜度：优先看 last_used_at，退回 updated_at；未知类型按 fact 阈值 */
export function getFreshness(memory: {
  type?: string | null
  last_used_at?: string | null
  updated_at?: string | null
}): Freshness {
  const t = FRESHNESS_THRESHOLDS[memory.type || 'fact'] || FRESHNESS_THRESHOLDS.fact
  const dateStr = memory.last_used_at || memory.updated_at
  if (!dateStr) return 'stale'
  const days = (Date.now() - new Date(ensureUtc(dateStr)).getTime()) / 86400000
  if (days < t.fresh) return 'fresh'
  if (days < t.aging) return 'aging'
  return 'stale'
}
