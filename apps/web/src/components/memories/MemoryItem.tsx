/* eslint-disable react-refresh/only-export-components */
import { memo } from 'react'
import { motion } from 'framer-motion'
import { spring } from '../../lib/motion'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { type MemoryListRecord } from '../../lib/api/memories'
import { typeLabel, sourceLabel, SOURCE_COLORS, TYPE_COLORS } from '../../lib/labels'
import { formatTime, formatRelativeTime, ensureUtc } from '../../lib/format'
import { Badge } from '../ui/Badge'
import { Checkbox } from '../ui/Checkbox'
import SearchHighlight from '../SearchHighlight'

export function getFreshness(memory: MemoryListRecord): 'fresh' | 'aging' | 'stale' {
  const type = memory.type || 'fact'
  const thresholds: Record<string, { fresh: number; aging: number }> = {
    fact: { fresh: 30, aging: 90 },
    reference: { fresh: 30, aging: 90 },
    decision: { fresh: 60, aging: 180 },
    convention: { fresh: 60, aging: 180 },
    pattern: { fresh: 60, aging: 180 },
    issue: { fresh: 30, aging: 90 },
    procedure: { fresh: 30, aging: 90 },
    feedback: { fresh: 30, aging: 90 },
  }
  const t = thresholds[type] || thresholds.fact
  const dateStr = memory.last_used_at || memory.updated_at
  if (!dateStr) return 'stale'
  const days = (Date.now() - new Date(ensureUtc(dateStr)).getTime()) / 86400000
  if (days < t.fresh) return 'fresh'
  if (days < t.aging) return 'aging'
  return 'stale'
}

export const MEMORY_TYPES = [
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
]

export interface MemoryItemProps {
  memory: MemoryListRecord
  idx: number
  selected: boolean
  focused: boolean
  query: string
  onToggle: (id: string) => void
  onOpen: (memory: MemoryListRecord) => void
}

const MemoryItem = memo(function MemoryItem({
  memory: m,
  idx,
  selected,
  focused,
  query,
  onToggle,
  onOpen,
}: MemoryItemProps) {
  const { t, locale } = useTranslation()
  const statusKey = m.status || 'active'
  const statusLbl =
    statusKey === 'deprecated'
      ? t.memories.statusDeprecated
      : statusKey === 'archived'
        ? t.memories.statusArchived
        : t.memories.statusActive
  const statusVariant =
    statusKey === 'deprecated'
      ? ('warning' as const)
      : statusKey === 'archived'
        ? ('default' as const)
        : ('success' as const)
  const freshness = getFreshness(m)
  const freshnessColor =
    freshness === 'fresh' ? 'bg-success' : freshness === 'aging' ? 'bg-warning' : 'bg-danger'

  // 效用分（价值）：≥0.5 绿 / 0.3-0.5 黄 / <0.3 与 null 灰。
  // null 表示聚合降级未算出，不是 0 分，展示为「—」且不画进度条
  const utility = m.utility_score ?? null
  const utilityPct = utility != null ? Math.round(utility * 100) : null
  const utilityVariant: 'success' | 'warning' | 'default' =
    utility == null ? 'default' : utility >= 0.5 ? 'success' : utility >= 0.3 ? 'warning' : 'default'
  // Tailwind 3 无法对 currentColor 附加透明度，轨道色按分档显式映射，条形用 bg-current
  const utilityTrackColor =
    utilityVariant === 'success'
      ? 'bg-success/30'
      : utilityVariant === 'warning'
        ? 'bg-warning/30'
        : 'bg-[var(--text-tertiary)]/25'
  return (
    <motion.div
      data-memory-index={idx}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay: Math.min(idx * 0.03, 0.3) }}
      layout
      onClick={() => onOpen(m)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(m)
        }
      }}
      role="button"
      tabIndex={0}
      className={`group px-4 py-3 cursor-pointer transition-all duration-200 relative border-b border-[var(--border-default)] last:border-b-0 ${
        selected ? 'bg-brand-50/30 border-l-[3px] border-l-brand-400' : ''
      } ${focused ? 'ring-2 ring-inset ring-brand-300/50 bg-surface-inset/50' : ''}`}
      whileHover={{
        x: 2,
        backgroundColor: selected
          ? undefined
          : `rgb(${getComputedStyle(document.documentElement).getPropertyValue('--brand-rgb').trim()} / 0.06)`,
        transition: { type: 'spring', stiffness: 400, damping: 25 },
      }}
    >
      <span
        className={`absolute left-0 top-1/2 -translate-y-1/2 w-[3px] rounded-full bg-brand-400 transition-all duration-200 ${
          selected ? 'h-5 opacity-100' : 'h-5 opacity-0 group-hover:opacity-60 group-hover:h-7'
        }`}
      />
      <div className="flex items-start gap-3 group-hover:translate-x-0.5 transition-transform duration-200">
        <span className="mt-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
          <Checkbox checked={selected} onCheckedChange={() => onToggle(m.id)} />
        </span>
        <div className="min-w-0 flex-1">
          {/* 标题行 */}
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-semibold tracking-[-0.01em] text-[var(--text-primary)] break-words leading-snug">
              <motion.span layoutId={`mem-title-${m.id}`} className="inline-block">
                <SearchHighlight text={m.title} query={query} />
              </motion.span>
            </h3>
            <div className="flex items-center gap-1.5 shrink-0">
              {m.is_permanent && (
                <span className="text-warning-fg" title={t.memories.permanentMark}>
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    aria-hidden="true"
                  >
                    <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                  </svg>
                </span>
              )}
              {m.confidence != null && (
                <span className="text-xs text-[var(--text-tertiary)] tabular-nums font-medium">
                  {Math.round((m.confidence || 0) * 100)}%
                </span>
              )}
            </div>
          </div>
          {/* 徽标行 */}
          <div className="flex flex-wrap items-center gap-1.5 mt-2">
            <Badge className={TYPE_COLORS[m.type] || ''}>{typeLabel(t.common, m.type)}</Badge>
            <Badge variant={statusVariant}>{statusLbl}</Badge>
            <Badge className={SOURCE_COLORS[m.source || ''] || ''}>
              {sourceLabel(t.common, m.source || '')}
            </Badge>
            <Badge
              variant={utilityVariant}
              className={utility == null ? 'text-[var(--text-tertiary)]' : ''}
              title={t.memories.utilityScore}
            >
              {utility != null && (
                <span
                  className={`relative inline-flex w-9 h-1.5 rounded-full overflow-hidden shrink-0 ${utilityTrackColor}`}
                  aria-hidden="true"
                >
                  <span
                    className="absolute inset-y-0 left-0 rounded-full bg-current"
                    style={{ width: `${utilityPct}%` }}
                  />
                </span>
              )}
              <span className="tabular-nums">{utility != null ? `${utilityPct}%` : '—'}</span>
            </Badge>
            {m.workspace && (
              <Badge variant="success" className="max-w-[120px] truncate">
                {m.workspace}
              </Badge>
            )}
          </div>
          {/* 元信息行 */}
          <div className="flex items-center gap-2 mt-2">
            <span
              className={`inline-flex items-center justify-center w-4 h-4 rounded-full ${freshnessColor}/15 shrink-0`}
              title={freshness}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${freshnessColor} ${freshness === 'fresh' ? 'animate-pulse' : ''}`}
              />
            </span>
            <span className="text-xs text-[var(--text-tertiary)] font-medium">
              {formatTime(m.updated || m.updated_at || '', locale)}
            </span>
            {m.last_used_at && (
              <span
                className="text-xs text-[var(--text-tertiary)] font-medium"
                title={`${t.memories.lastUsed} · ${formatTime(m.last_used_at, locale)}`}
              >
                {t.memories.lastUsed}{' '}
                {formatRelativeTime(
                  m.last_used_at,
                  {
                    justNow: t.common.justNow,
                    minutesAgo: t.common.minutesAgo,
                    hoursAgo: t.common.hoursAgo,
                    daysAgo: t.common.daysAgo,
                  },
                  locale,
                )}
              </span>
            )}
            {m.version && (
              <span className="text-xs text-[var(--text-tertiary)] font-medium">v{m.version}</span>
            )}
            {m.usage_count != null && m.usage_count > 0 && (
              <span className="text-xs text-[var(--text-tertiary)] font-medium">
                {translate(t.memories.usedTimes, { n: m.usage_count })}
              </span>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  )
})

export default MemoryItem
