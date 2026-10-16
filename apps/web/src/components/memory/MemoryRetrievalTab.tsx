import { useState } from 'react'
import { Check, Minus, Search } from 'lucide-react'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { formatRelativeTime } from '../../lib/format'
import { Button } from '../ui/Button'
import { TabContentSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import EmptyState from '../EmptyState'
import { useMemoryRetrievalHistory } from '../../hooks/useMemoryDetail'
import type { MemoryRetrievalHitItem } from '../../lib/api/memories'

// 后端 limit 上限 20（ge=1 le=20），"加载更多"按 5 条递增
const PAGE_STEP = 5
const MAX_LIMIT = 20

// signals 的固定展示顺序；字典里不存在的 key 不渲染（有值才显示）
const SIGNAL_KEYS = ['bm25', 'vector', 'rrf', 'rerank', 'utility'] as const

// filter_reasons.stage → i18n key（来源：packages/retrieval/context 组装器与入口过滤）
const STAGE_I18N_KEYS: Record<
  string,
  | 'filterStageStale'
  | 'filterStageConfidence'
  | 'filterStageRelevance'
  | 'filterStageTruncated'
  | 'filterStageDedup'
  | 'filterStageDiversity'
  | 'filterStageCompress'
  | 'filterStageMerge'
  | 'filterStageDegrade'
> = {
  stale: 'filterStageStale',
  confidence: 'filterStageConfidence',
  relevance_floor: 'filterStageRelevance',
  truncated: 'filterStageTruncated',
  dedup: 'filterStageDedup',
  diversity: 'filterStageDiversity',
  compress: 'filterStageCompress',
  merge: 'filterStageMerge',
  degrade: 'filterStageDegrade',
}

// filter_reasons.reason → i18n key（无参数的精确匹配项）
const REASON_I18N_KEYS: Record<
  string,
  | 'filterReasonExpired'
  | 'filterReasonExpiredDemoted'
  | 'filterReasonBelowConfidence'
  | 'filterReasonLowConfidence'
  | 'filterReasonBelowRelevance'
  | 'filterReasonLowRelevance'
  | 'filterReasonOverBudget'
  | 'filterReasonDuplicateRemoved'
  | 'filterReasonMaxPerType'
  | 'filterReasonContentTrimmed'
  | 'filterReasonMerged'
  | 'filterReasonDegradedSummary'
  | 'filterReasonDegradedTitle'
> = {
  expired: 'filterReasonExpired',
  expired_demoted: 'filterReasonExpiredDemoted',
  below_confidence_floor: 'filterReasonBelowConfidence',
  low_confidence_demoted: 'filterReasonLowConfidence',
  below_relevance_floor: 'filterReasonBelowRelevance',
  low_relevance_demoted: 'filterReasonLowRelevance',
  over_budget: 'filterReasonOverBudget',
  duplicate_removed: 'filterReasonDuplicateRemoved',
  max_per_type: 'filterReasonMaxPerType',
  content_trimmed: 'filterReasonContentTrimmed',
  merged: 'filterReasonMerged',
  degraded_to_summary: 'filterReasonDegradedSummary',
  degraded_to_title: 'filterReasonDegradedTitle',
}

// UUID 过长，展示时截断；类型名等短值原样保留
function shortTarget(value: string): string {
  return value.length > 10 ? `${value.slice(0, 8)}…` : value
}

function filterReasonLabel(
  stage: string,
  reason: string,
  t: ReturnType<typeof useTranslation>['t'],
): string {
  // 带参数的 reason：duplicate_of:{id} / max_per_type:{type} / merged_into:{id}
  const colonIdx = reason.indexOf(':')
  if (colonIdx > 0) {
    const prefix = reason.slice(0, colonIdx)
    const target = reason.slice(colonIdx + 1)
    if (prefix === 'duplicate_of')
      return translate(t.memoryDetail.filterReasonDuplicateOf, { target: shortTarget(target) })
    if (prefix === 'merged_into')
      return translate(t.memoryDetail.filterReasonMergedInto, { target: shortTarget(target) })
    if (prefix === 'max_per_type') return t.memoryDetail.filterReasonMaxPerType
  }
  const key = REASON_I18N_KEYS[reason]
  return key ? t.memoryDetail[key] : reason || stage
}

interface Props {
  memoryId: string
}

export default function MemoryRetrievalTab({ memoryId }: Props) {
  const { t, locale } = useTranslation()
  const [limit, setLimit] = useState(PAGE_STEP)
  const { data, loading, error, reload } = useMemoryRetrievalHistory(memoryId, limit)

  if (loading && !data) return <TabContentSkeleton />
  // 已有数据时加载更多失败不清空列表，行内提示重试
  if (error && !data)
    return (
      <ErrorAlert
        message={t.memoryDetail.retrievalLoadFailed}
        onRetry={reload}
        retryLabel={t.common.retry}
      />
    )
  if (!data || data.items.length === 0)
    return (
      <EmptyState
        icon={<Search size={22} className="text-[var(--text-tertiary)]" />}
        message={t.memoryDetail.retrievalEmpty}
        compact
      />
    )

  const hasMore = data.total > data.items.length
  const canLoadMore = hasMore && limit < MAX_LIMIT

  return (
    <div className="space-y-2.5">
      {hasMore && (
        <div className="text-xs text-[var(--text-tertiary)] tabular-nums">
          {translate(t.memoryDetail.retrievalTotal, { n: data.total })}
        </div>
      )}
      <ul className="space-y-1.5">
        {data.items.map((item) => (
          <RetrievalHitRow
            key={`${item.trace_id}-${item.rank ?? 'x'}`}
            item={item}
            locale={locale}
          />
        ))}
      </ul>
      {canLoadMore && (
        <div className="flex justify-center pt-1">
          <Button variant="secondary" size="sm" onClick={() => setLimit((v) => v + PAGE_STEP)}>
            {t.memoryDetail.retrievalLoadMore}
          </Button>
        </div>
      )}
      {error && data && (
        <div className="flex items-center justify-center gap-2 text-xs text-danger-fg">
          {t.memoryDetail.retrievalLoadFailed}
          <button
            type="button"
            onClick={reload}
            className="px-1.5 py-0.5 rounded-md hover:bg-surface-inset transition-colors duration-150"
          >
            {t.common.retry}
          </button>
        </div>
      )}
    </div>
  )
}

function RetrievalHitRow({ item, locale }: { item: MemoryRetrievalHitItem; locale: string }) {
  const { t } = useTranslation()

  return (
    <li className="rounded-lg bg-surface-inset border border-[var(--border-default)] shadow-warm-xs px-3 py-2.5 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <UsedBadge used={item.used} />
        <span
          className="font-mono text-sm text-[var(--text-primary)] truncate min-w-0 flex-1"
          title={item.query}
        >
          {item.query}
        </span>
        <span className="text-2xs text-[var(--text-tertiary)] tabular-nums shrink-0">
          {formatRelativeTime(item.retrieved_at, t.common, locale)}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-[var(--text-secondary)]">
        {item.rank != null && (
          <span className="font-medium">
            {translate(t.memoryDetail.retrievalRank, { n: item.rank })}
          </span>
        )}
        {item.score != null && (
          <span className="tabular-nums">
            {t.memoryDetail.retrievalScore} {item.score.toFixed(3)}
          </span>
        )}
        {SIGNAL_KEYS.map((key) =>
          item.signals[key] != null ? (
            <span key={key} className="tabular-nums">
              {key}
              <span className="ml-1 text-[var(--text-tertiary)]">
                {item.signals[key].toFixed(3)}
              </span>
            </span>
          ) : null,
        )}
      </div>
      {item.filter_reasons.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {item.filter_reasons.map((fr, i) => {
            const stageKey = STAGE_I18N_KEYS[fr.stage]
            const stageLabel = stageKey ? t.memoryDetail[stageKey] : fr.stage
            return (
              <span
                key={i}
                className="inline-flex items-center px-1.5 py-0.5 rounded-md text-3xs bg-warning/15 border border-warning/30 text-warning-fg"
                title={`${fr.stage}: ${fr.reason}`}
              >
                {stageLabel} · {filterReasonLabel(fr.stage, fr.reason, t)}
              </span>
            )
          })}
        </div>
      )}
    </li>
  )
}

// used 状态：颜色 + 文字 + 图标三重区分，未使用为弱化灰
function UsedBadge({ used }: { used: boolean }) {
  const { t } = useTranslation()
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-2xs font-medium border shrink-0 ${
        used
          ? 'bg-success/18 border-success/35 text-success-fg'
          : 'bg-surface-elevated/60 border-[var(--border-default)] text-[var(--text-tertiary)]'
      }`}
    >
      {used ? <Check size={10} aria-hidden="true" /> : <Minus size={10} aria-hidden="true" />}
      {used ? t.memoryDetail.retrievalUsed : t.memoryDetail.retrievalUnused}
    </span>
  )
}
