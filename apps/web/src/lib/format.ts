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
