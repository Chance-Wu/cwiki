import { useState, useEffect, useCallback } from 'react'
import { EmptyHealth } from '../EmptyIllustrations'
import { api, type MemoryHealth } from '../../lib/api'
import { useTranslation } from '../../i18n/I18nProvider'
import { TabContentSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import EmptyState from '../EmptyState'
import StatBox from '../StatBox'

interface Props {
  memoryId: string
}

export default function MemoryHealthTab({ memoryId }: Props) {
  const { t } = useTranslation()
  const [data, setData] = useState<MemoryHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const result = await api.getMemoryHealth(memoryId)
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
        message={t.memories.loadHealthFailed}
        onRetry={fetchData}
        retryLabel={t.common.retry}
      />
    )
  if (!data) return <EmptyState illustration={<EmptyHealth />} message={t.memories.noHealth} />

  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        <StatBox
          value={data.health?.score != null ? Math.round(data.health.score * 100) : 0}
          label={t.memories.healthScore}
          color="success"
          className="flex-1"
        />
        <StatBox
          value={data.utility?.utility != null ? Math.round(data.utility.utility * 100) : 0}
          label={t.memories.utilityScore}
          color="brand"
          className="flex-1"
        />
      </div>
      {(data.health?.reasons?.length ?? 0) > 0 && (
        <div>
          <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
            {t.memories.healthScore}
          </h4>
          <ul className="space-y-1">
            {(data.health?.reasons ?? []).map((reason, i) => (
              <li
                key={i}
                className="text-sm text-[var(--text-secondary)] flex items-start gap-2 px-2 py-1 -mx-2 rounded-lg hover:bg-surface-inset transition-all duration-150 active:scale-[0.98]"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-tertiary)] mt-1.5 shrink-0" />
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
