/* eslint-disable react-refresh/only-export-components */
import { memo } from 'react'
import { motion } from 'framer-motion'
import { spring } from '../../lib/motion'
import { useTranslation } from '../../i18n/I18nProvider'
import { type MemoryListRecord } from '../../lib/api/memories'
import { typeLabel, sourceLabel, SOURCE_COLORS, TYPE_COLORS } from '../../lib/labels'
import { ensureUtc, formatRelativeTime } from '../../lib/format'
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
  const { t } = useTranslation()
  const statusKey = m.status || 'active'
  const statusLbl =
    statusKey === 'deprecated'
      ? t.memories.statusDeprecated
      : statusKey === 'archived'
        ? t.memories.statusArchived
        : t.memories.statusActive

  // 效用分（价值）：≥0.5 绿 / 0.3-0.5 黄 / <0.3 与 null 灰。
  // null 表示聚合降级未算出，不是 0 分，展示为「—」且不画进度条
  const utility = m.utility_score ?? null
  const utilityPct = utility != null ? Math.round(utility * 100) : null
  const utilityVariant: 'success' | 'warning' | 'default' =
    utility == null
      ? 'default'
      : utility >= 0.5
        ? 'success'
        : utility >= 0.3
          ? 'warning'
          : 'default'
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
          {/* 徽标行：合并类型+状态，省略默认来源 */}
          <div className="flex flex-wrap items-center gap-1.5 mt-2">
            {/* 类型·状态合并 */}
            <Badge className={TYPE_COLORS[m.type] || ''}>
              {typeLabel(t.common, m.type)}
              <span className="opacity-60 mx-1">·</span>
              <span className="opacity-90">{statusLbl}</span>
            </Badge>
            {/* 来源：仅显示非默认来源 */}
            {m.source && m.source !== 'memory_save' && (
              <Badge className={SOURCE_COLORS[m.source] || ''}>
                {sourceLabel(t.common, m.source)}
              </Badge>
            )}
            {/* 标签：最多显示 2 个，其余省略 */}
            {Array.isArray(m.tags) && m.tags.length > 0 && (
              <>
                {m.tags.slice(0, 2).map((tag) => (
                  <Badge
                    key={tag}
                    variant="default"
                    className="bg-brand-badge-bg text-brand-badge-text border-brand-border text-[10px] px-1.5 py-0"
                    title={`标签 (${m.tags!.length}): ${m.tags!.join(', ')}`}
                  >
                    {tag}
                  </Badge>
                ))}
                {m.tags.length > 2 && (
                  <Badge
                    variant="default"
                    className="bg-surface-inset text-[var(--text-tertiary)] border-[var(--border-default)] text-[10px] px-1.5 py-0"
                    title={`标签 (${m.tags!.length}): ${m.tags!.join(', ')}`}
                  >
                    +{m.tags.length - 2}
                  </Badge>
                )}
              </>
            )}
            {/* 效用分：只显示进度条 */}
            {utility != null && (
              <div className="flex items-center gap-1" title={t.memories.utilityScore}>
                <div
                  className={`relative inline-flex w-8 h-1 rounded-full overflow-hidden ${utilityTrackColor}`}
                  aria-hidden="true"
                >
                  <div
                    className="absolute inset-y-0 left-0 rounded-full bg-current"
                    style={{ width: `${utilityPct}%` }}
                  />
                </div>
              </div>
            )}
            {/* 匹配分：仅搜索结果携带 */}
            {m.score != null && (
              <Badge
                variant={m.score >= 0.5 ? 'success' : m.score >= 0.3 ? 'warning' : 'default'}
                title={t.memories.matchScore}
                className="text-[10px] px-1.5 py-0"
              >
                <span className="tabular-nums">{Math.round(m.score * 100)}%</span>
              </Badge>
            )}
          </div>
          {/* 第二行：工作区 + 时间 */}
          <div className="flex items-center gap-2 mt-1.5 text-[10px] text-[var(--text-tertiary)]">
            {m.workspace && (
              <span className="truncate max-w-[100px]" title={m.workspace}>
                {m.workspace}
              </span>
            )}
            {m.updated_at && (
              <span title={new Date(ensureUtc(m.updated_at)).toLocaleString('zh-CN')}>
                {formatRelativeTime(m.updated_at, {
                  justNow: t.common.justNow,
                  minutesAgo: t.common.minutesAgo,
                  hoursAgo: t.common.hoursAgo,
                  daysAgo: t.common.daysAgo,
                }, 'zh')}
              </span>
            )}
            {m.usage_count != null && m.usage_count > 0 && <span>已用 {m.usage_count} 次</span>}
          </div>
        </div>
      </div>
    </motion.div>
  )
})

export default MemoryItem
