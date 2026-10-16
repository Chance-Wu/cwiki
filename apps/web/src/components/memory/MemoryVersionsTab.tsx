import { useState, useEffect, useCallback } from 'react'
import { EmptyVersions } from '../EmptyIllustrations'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { api, type MemoryVersion } from '../../lib/api'
import { formatTime } from '../../lib/format'
import { useTranslation } from '../../i18n/I18nProvider'
import { TabContentSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import EmptyState from '../EmptyState'
import MarkdownContent from '../MarkdownContent'

interface Props {
  memoryId: string
}

export default function MemoryVersionsTab({ memoryId }: Props) {
  const { t, locale } = useTranslation()
  const [versions, setVersions] = useState<MemoryVersion[]>([])
  const [expandedVersion, setExpandedVersion] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const fetchVersions = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await api.getMemoryVersions(memoryId, 50)
      setVersions(data || [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [memoryId])

  useEffect(() => {
    fetchVersions()
  }, [fetchVersions])

  if (loading) return <TabContentSkeleton />
  if (error)
    return (
      <ErrorAlert
        message={t.memories.loadVersionsFailed}
        onRetry={fetchVersions}
        retryLabel={t.common.retry}
      />
    )
  if (versions.length === 0)
    return <EmptyState illustration={<EmptyVersions />} message={t.memories.noVersions} />

  return (
    <div className="relative space-y-0">
      <div className="absolute left-[7px] top-2 bottom-2 w-px bg-gradient-to-b from-transparent via-[var(--border-default)] to-transparent" />
      {versions.map((v) => (
        <div key={v.id} className="relative pl-6 pb-4 last:pb-0">
          <div className="absolute left-0 top-1.5 w-3.5 h-3.5 rounded-full border-2 border-[var(--surface-card)] bg-[var(--text-tertiary)]" />
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-[var(--text-primary)]">v{v.version}</span>
            <Badge
              className={
                v.change_type === 'created'
                  ? 'bg-success/22 text-success-fg border border-success/35'
                  : v.change_type === 'updated'
                    ? 'bg-info/22 text-info-fg border border-info/35'
                    : ''
              }
            >
              {v.change_type}
            </Badge>
            <span className="text-sm text-[var(--text-tertiary)] ml-auto">
              {formatTime(v.created_at, locale)}
            </span>
          </div>
          {v.reason && <p className="text-base text-[var(--text-secondary)] mb-1">{v.reason}</p>}
          <Button
            onClick={() => setExpandedVersion(expandedVersion === v.id ? null : v.id)}
            variant="ghost"
            size="sm"
          >
            {expandedVersion === v.id ? t.common.collapse : t.common.expand}
          </Button>
          {expandedVersion === v.id && (
            <div className="mt-2 p-3 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs animate-[fade-in_0.2s_ease-out]">
              <h5 className="text-sm font-medium text-[var(--text-secondary)] mb-2">{v.title}</h5>
              <div className="text-sm text-[var(--text-secondary)] prose prose-sm max-w-none">
                <MarkdownContent content={v.content} />
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
