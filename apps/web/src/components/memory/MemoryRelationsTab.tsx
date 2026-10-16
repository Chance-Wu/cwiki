import { useState, useEffect, useCallback } from 'react'
import { EmptyRelations } from '../EmptyIllustrations'
import { api, type Relation, type RelatedMemory } from '../../lib/api'
import { typeLabel, TYPE_COLORS } from '../../lib/labels'
import { useTranslation } from '../../i18n/I18nProvider'
import { TabContentSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import EmptyState from '../EmptyState'

interface Props {
  memoryId: string
  onNavigateToMemory?: (memoryId: string) => void
}

export default function MemoryRelationsTab({ memoryId, onNavigateToMemory }: Props) {
  const { t } = useTranslation()
  const [relations, setRelations] = useState<Relation[]>([])
  const [relatedMemories, setRelatedMemories] = useState<RelatedMemory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await api.getMemoryRelations(memoryId)
      setRelations(data.relations || [])
      setRelatedMemories(data.related_memories || [])
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
        message={t.memories.loadRelationsFailed}
        onRetry={fetchData}
        retryLabel={t.common.retry}
      />
    )
  if (relations.length === 0 && relatedMemories.length === 0)
    return <EmptyState illustration={<EmptyRelations />} message={t.memories.noRelations} />

  return (
    <div className="space-y-4">
      {relatedMemories.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
            {t.memories.relatedMemories}
          </h4>
          <div className="space-y-3">
            {relatedMemories.map((m) => (
              <div
                key={m.id}
                onClick={() => onNavigateToMemory?.(m.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onNavigateToMemory?.(m.id)
                  }
                }}
                className="group relative flex items-center gap-2 p-2 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs hover:bg-brand-50/20 cursor-pointer transition-all duration-150 active:scale-[0.98]"
              >
                <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-4 rounded-full bg-brand-400 opacity-40 transition-opacity duration-150" />
                <span
                  className={`px-1.5 py-0.5 text-sm rounded-lg border ${TYPE_COLORS[m.type] || 'bg-surface-inset text-[var(--text-secondary)] border-[var(--border-default)]'}`}
                >
                  {typeLabel(t.common, m.type)}
                </span>
                <span className="text-sm text-[var(--text-primary)] truncate flex-1">
                  {m.title}
                </span>
                <svg
                  className="w-4 h-4 text-[var(--text-tertiary)] shrink-0"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              </div>
            ))}
          </div>
        </div>
      )}
      {relations.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
            {t.memories.relationType}
          </h4>
          <div className="space-y-3">
            {relations.map((r) => (
              <div
                key={r.id}
                className="flex items-center gap-3 text-base p-2 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs"
              >
                <span className="px-1.5 py-0.5 text-sm bg-surface-card text-[var(--text-primary)] rounded-lg border border-[var(--glass-border)]">
                  {r.relation_type}
                </span>
                <span className="text-[var(--text-secondary)]">
                  {t.memories.relationConfidence}:{' '}
                  <span className="tabular-nums">{Math.round(r.confidence * 100)}</span>%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
