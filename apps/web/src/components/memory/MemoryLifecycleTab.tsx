import { useState, useEffect, useCallback } from 'react'
import { EmptyTimeline } from '../EmptyIllustrations'
import { api, type Lifecycle } from '../../lib/api'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { formatTime } from '../../lib/format'
import { TabContentSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import EmptyState from '../EmptyState'
import StatBox from '../StatBox'

interface Props {
  memoryId: string
}

const STATUS_CONFIG: Record<
  string,
  { labelKey: string; color: 'success' | 'warning' | 'danger' | 'info' | 'brand' }
> = {
  active: { labelKey: 'statusActive', color: 'success' },
  archived: { labelKey: 'archived', color: 'info' },
  deprecated: { labelKey: 'statusDeprecated', color: 'warning' },
  superseded: { labelKey: 'statusSuperseded', color: 'danger' },
  conflicted: { labelKey: 'statusConflicted', color: 'danger' },
}

const EVENT_CONFIG: Record<string, { labelKey: string; icon: string; color: string }> = {
  created: { labelKey: 'eventCreated', icon: '', color: 'bg-success' },
  updated: { labelKey: 'eventUpdated', icon: '✎', color: 'bg-brand-500' },
  status_changed: { labelKey: 'eventStatusChanged', icon: '⟳', color: 'bg-warning' },
  merged: { labelKey: 'eventMerged', icon: '⊕', color: 'bg-info' },
  archived: { labelKey: 'eventArchived', icon: '◼', color: 'bg-[var(--text-tertiary)]' },
  deprecated: { labelKey: 'eventDeprecated', icon: '⊘', color: 'bg-warning' },
  restored: { labelKey: 'eventRestored', icon: '↺', color: 'bg-success' },
  reviewed: { labelKey: 'eventReviewed', icon: '✓', color: 'bg-brand-500' },
}

function getEventConfig(eventType: string) {
  for (const key of Object.keys(EVENT_CONFIG)) {
    if (eventType.includes(key)) return EVENT_CONFIG[key]
  }
  return { labelKey: '', icon: '●', color: 'bg-[var(--text-tertiary)]' }
}

function getStatusConfig(status: string) {
  return STATUS_CONFIG[status] || { labelKey: status, color: 'info' as const }
}

function formatMetadata(metadata: Record<string, unknown> | null): string | null {
  if (!metadata) return null
  const parts: string[] = []
  if (metadata.old_status && metadata.new_status) {
    parts.push(`${metadata.old_status} → ${metadata.new_status}`)
  }
  if (metadata.reason) {
    parts.push(String(metadata.reason))
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

export default function MemoryLifecycleTab({ memoryId }: Props) {
  const { t, locale } = useTranslation()
  const [data, setData] = useState<Lifecycle | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const result = await api.getMemoryLifecycle(memoryId)
      setData(result)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [memoryId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (loading) return <TabContentSkeleton />
  if (error)
    return (
      <ErrorAlert
        message={t.memories.loadLifecycleFailed}
        onRetry={fetchData}
        retryLabel={t.common.retry}
      />
    )
  if (!data) return <TabContentSkeleton />

  const statusConfig = getStatusConfig(data.current_status)
  const statusLabel =
    (t.memory.lifecycle as Record<string, string>)[statusConfig.labelKey] ?? statusConfig.labelKey

  return (
    <div className="space-y-4">
      {/* 状态与统计 */}
      <div className="flex gap-4">
        <div className="flex-1">
          <div className="text-xs font-medium text-[var(--text-tertiary)] mb-1.5">
            {t.memories.lifecycleStatus}
          </div>
          <div
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium ${
              statusConfig.color === 'success'
                ? 'bg-success/10 text-success-fg'
                : statusConfig.color === 'warning'
                  ? 'bg-warning/10 text-warning-fg'
                  : statusConfig.color === 'danger'
                    ? 'bg-danger/10 text-danger-fg'
                    : 'bg-info/10 text-info-fg'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            {statusLabel}
          </div>
        </div>
        <StatBox
          value={
            data.age_days != null ? translate(t.memories.lifecycleDays, { n: data.age_days }) : '—'
          }
          label={t.memories.lifecycleAge}
          color="brand"
          className="flex-1"
        />
        <StatBox
          value={data.event_count}
          label={t.memories.lifecycleEvents}
          color="blue"
          className="flex-1"
        />
      </div>

      {/* 生命周期时间线 */}
      {(data.timeline?.length ?? 0) > 0 ? (
        <div>
          <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-3">
            {t.memories.lifecycleEvents}
          </h4>
          <div className="relative space-y-0">
            <div className="absolute left-[11px] top-2 bottom-2 w-px bg-gradient-to-b from-transparent via-[var(--border-default)] to-transparent" />
            {(data.timeline ?? []).map((event, i) => {
              const config = getEventConfig(event.event_type)
              const eventLabel = config.labelKey
                ? ((t.memory.lifecycle as Record<string, string>)[config.labelKey] ??
                  config.labelKey)
                : event.event_type
              const meta = formatMetadata(event.metadata)
              return (
                <div key={i} className="relative pl-8 pb-4 last:pb-0">
                  {/* 事件圆点 */}
                  <div
                    className={`absolute left-0 top-1.5 w-5 h-5 rounded-full border-2 border-[var(--surface-card)] ${config.color} ${
                      i === 0
                        ? ' ring-2 ring-brand-200 animate-[pulse_2s_ease-in-out_infinite]'
                        : ''
                    }`}
                  >
                    <span className="flex items-center justify-center h-full text-[10px] text-white font-bold">
                      {config.icon}
                    </span>
                  </div>
                  {/* 事件内容 */}
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        {eventLabel}
                      </span>
                      {event.timestamp && (
                        <span className="text-xs text-[var(--text-tertiary)] ml-auto">
                          {formatTime(event.timestamp, locale)}
                        </span>
                      )}
                    </div>
                    {meta && (
                      <div className="text-xs text-[var(--text-secondary)] pl-0.5">{meta}</div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <EmptyState illustration={<EmptyTimeline />} message={t.memories.lifecycleNoEvents} />
      )}
    </div>
  )
}
