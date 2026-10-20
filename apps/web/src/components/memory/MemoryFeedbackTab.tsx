import { useState, useCallback, useEffect } from 'react'
import { ThumbsUp, ThumbsDown, Clock } from 'lucide-react'
import { api } from '../../lib/api'
import type { MemoryFeedbackItem } from '../../lib/api/memories'
import { useTranslation } from '../../i18n/I18nProvider'
import { formatRelativeTime } from '../../lib/format'
import { useToast } from '../Toast'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Badge } from '../ui/Badge'
import { SegmentedControl } from '../ui/SegmentedControl'
import { TabContentSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import { EmptyFeedback } from '../EmptyIllustrations'
import EmptyState from '../EmptyState'
import StatBox from '../StatBox'
import { useMemoryFeedbackDetail } from '../../hooks/useMemoryDetail'

interface FeedbackSummary {
  useful?: number
  not_useful?: number
  outdated?: number
  wrong?: number
  // 后端 /feedback/summary 返回 total，用于空态判断
  total?: number
}

type FeedbackIdentity = 'human' | 'agent'

// 反馈来源徽标：颜色 + 文字双重区分（人类=蓝、Agent=紫、自动=灰）。
// 不用 info 语义色：dark 模式下 info 会被主题翻成琥珀色，无法保证"蓝"
const SOURCE_BADGE_STYLES: Record<string, string> = {
  human: 'bg-blue-500/15 border-blue-500/30 text-blue-600 dark:text-blue-300',
  agent: 'bg-purple-500/15 border-purple-500/30 text-purple-600 dark:text-purple-300',
  auto: 'bg-surface-inset border-[var(--border-default)] text-[var(--text-tertiary)]',
}

// 反馈类型 → 徽标变体与 i18n key（复用 memories 命名空间的既有文案）
const FEEDBACK_TYPE_VARIANTS: Record<
  string,
  {
    variant: 'success' | 'danger' | 'warning'
    key: 'feedbackUseful' | 'feedbackNotUseful' | 'feedbackOutdated' | 'feedbackWrong'
  }
> = {
  useful: { variant: 'success', key: 'feedbackUseful' },
  not_useful: { variant: 'danger', key: 'feedbackNotUseful' },
  outdated: { variant: 'warning', key: 'feedbackOutdated' },
  wrong: { variant: 'danger', key: 'feedbackWrong' },
}

interface Props {
  memoryId: string
}

export default function MemoryFeedbackTab({ memoryId }: Props) {
  const { t, locale } = useTranslation()
  const { toast } = useToast()
  const [summary, setSummary] = useState<FeedbackSummary | null>(null)
  const [identity, setIdentity] = useState<FeedbackIdentity>('human')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  // 反馈明细独立于汇总加载：明细失败不阻塞计数与提交
  const detail = useMemoryFeedbackDetail(memoryId)

  const fetchSummary = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await api.getFeedbackSummary(memoryId)
      setSummary(data)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [memoryId])

  // 挂载/memoryId 变化时拉取汇总：无此调用 loading 恒为 true，tab 永远停在骨架屏
  useEffect(() => {
    fetchSummary()
  }, [fetchSummary])

  const handleFeedback = useCallback(
    async (type: string) => {
      setSubmitting(true)
      try {
        const wsId = (await api.getDefaultWorkspaceId()) || 'default'
        // 后端 MemoryFeedbackCreate 支持 source_type(human/agent/auto) 与 reason
        await api.createFeedback({
          workspace_id: wsId,
          memory_id: memoryId,
          feedback_type: type,
          source_type: identity,
          reason: reason.trim() || undefined,
        })
        setSummary(await api.getFeedbackSummary(memoryId))
        detail.reload()
      } catch {
        toast(t.memories.feedbackFailed, 'error')
      } finally {
        setSubmitting(false)
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [memoryId, identity, reason, detail.reload, toast, t.memories.feedbackFailed],
  )

  const submitArea = (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-[var(--text-tertiary)] shrink-0">
          {t.memoryDetail.feedbackIdentityLabel}
        </span>
        <SegmentedControl<FeedbackIdentity>
          value={identity}
          onChange={setIdentity}
          options={[
            { value: 'human', label: t.memoryDetail.feedbackSourceHuman },
            { value: 'agent', label: t.memoryDetail.feedbackSourceAgent },
          ]}
        />
        <Input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t.memoryDetail.feedbackReasonPlaceholder}
          maxLength={500}
          className="flex-1 min-w-[180px] text-sm"
        />
      </div>
      <div className="flex gap-2 justify-center">
        <Button
          variant="success"
          size="sm"
          onClick={() => handleFeedback('useful')}
          disabled={submitting}
        >
          <ThumbsUp size={14} aria-hidden="true" /> {t.memories.feedbackUseful}
        </Button>
        <Button
          variant="danger"
          size="sm"
          onClick={() => handleFeedback('not_useful')}
          disabled={submitting}
        >
          <ThumbsDown size={14} aria-hidden="true" /> {t.memories.feedbackNotUseful}
        </Button>
        <Button
          variant="warning"
          size="sm"
          onClick={() => handleFeedback('outdated')}
          disabled={submitting}
        >
          <Clock size={14} aria-hidden="true" /> {t.memories.feedbackOutdated}
        </Button>
      </div>
    </div>
  )

  if (loading) return <TabContentSkeleton />
  if (error)
    return (
      <ErrorAlert
        message={t.memories.loadFeedbackFailed}
        onRetry={fetchSummary}
        retryLabel={t.common.retry}
      />
    )

  const hasDetailItems = (detail.data?.items.length ?? 0) > 0
  const isEmpty = !summary || (summary.total ?? 0) === 0

  // 全空状态：保留插画式空态，附上提交区
  if (isEmpty && !hasDetailItems) {
    return (
      <EmptyState
        illustration={<EmptyFeedback />}
        message={t.memories.noFeedback}
        action={submitArea}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        <StatBox
          value={summary?.useful || 0}
          label={t.memories.feedbackUseful}
          color="success"
          className="flex-1"
        />
        <StatBox
          value={summary?.not_useful || 0}
          label={t.memories.feedbackNotUseful}
          color="danger"
          className="flex-1"
        />
        <StatBox
          value={summary?.outdated || 0}
          label={t.memories.feedbackOutdated}
          color="warning"
          className="flex-1"
        />
        <StatBox
          value={summary?.wrong || 0}
          label={t.memories.feedbackWrong}
          color="danger"
          className="flex-1"
        />
      </div>
      {submitArea}
      <FeedbackDetailList
        detail={detail.data}
        loading={detail.loading}
        error={detail.error}
        onRetry={detail.reload}
        locale={locale}
      />
    </div>
  )
}

interface DetailListProps {
  detail: { total: number; items: MemoryFeedbackItem[] } | null
  loading: boolean
  error: boolean
  onRetry: () => void
  locale: string
}

/** 反馈明细列表：父组件持有加载状态，这里纯展示（避免同端点重复请求） */
function FeedbackDetailList({ detail, loading, error, onRetry, locale }: DetailListProps) {
  const { t } = useTranslation()

  if (loading) {
    return <div className="text-xs text-[var(--text-tertiary)] py-1">{t.common.loading}</div>
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 text-xs text-danger-fg py-1">
        {t.memoryDetail.feedbackDetailLoadFailed}
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center px-1.5 py-0.5 rounded-md hover:bg-surface-inset transition-colors duration-150"
        >
          {t.common.retry}
        </button>
      </div>
    )
  }
  if (!detail || detail.items.length === 0) {
    return (
      <div className="text-xs text-[var(--text-tertiary)]">
        {t.memoryDetail.feedbackDetailEmpty}
      </div>
    )
  }

  return (
    <div>
      <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
        {t.memoryDetail.feedbackDetailTitle}
        <span className="ml-1.5 text-xs font-normal text-[var(--text-tertiary)] tabular-nums">
          {detail.total}
        </span>
      </h4>
      <ul className="space-y-1.5">
        {detail.items.map((item) => (
          <FeedbackItemRow key={item.id} item={item} locale={locale} />
        ))}
      </ul>
    </div>
  )
}

function FeedbackItemRow({ item, locale }: { item: MemoryFeedbackItem; locale: string }) {
  const { t } = useTranslation()

  const typeMeta = FEEDBACK_TYPE_VARIANTS[item.feedback_type]
  const typeLabel = typeMeta ? t.memories[typeMeta.key] : item.feedback_type || '-'

  const sourceStyle =
    SOURCE_BADGE_STYLES[item.source_type] ||
    'bg-surface-elevated/60 border-[var(--glass-border)] text-[var(--text-secondary)]'
  const sourceLabel =
    item.source_type === 'human'
      ? t.memoryDetail.feedbackSourceHuman
      : item.source_type === 'agent'
        ? t.memoryDetail.feedbackSourceAgent
        : item.source_type === 'auto'
          ? t.memoryDetail.feedbackSourceAuto
          : item.source_type

  return (
    <li className="flex flex-wrap items-start gap-x-2 gap-y-1 rounded-lg bg-surface-inset border border-[var(--border-default)] shadow-warm-xs px-3 py-2">
      <Badge variant={typeMeta?.variant || 'default'} className="shrink-0">
        {typeLabel}
      </Badge>
      <span
        className={`inline-flex items-center px-1.5 py-0.5 rounded-md text-2xs font-medium border shrink-0 ${sourceStyle}`}
      >
        {sourceLabel}
      </span>
      {item.source_id && (
        <span
          className="text-2xs font-mono text-[var(--text-secondary)] self-center max-w-[200px] truncate"
          title={item.source_id}
        >
          {item.source_id}
        </span>
      )}
      <span className="ml-auto text-2xs text-[var(--text-tertiary)] tabular-nums self-center shrink-0">
        {formatRelativeTime(item.created_at, t.common, locale)}
      </span>
      {item.reason && (
        <p className="w-full text-xs text-[var(--text-secondary)] leading-relaxed break-words pl-0.5">
          {item.reason}
        </p>
      )}
    </li>
  )
}
