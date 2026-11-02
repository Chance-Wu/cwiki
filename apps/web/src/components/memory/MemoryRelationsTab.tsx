import { useState, useEffect, useCallback } from 'react'
import { EmptyRelations } from '../EmptyIllustrations'
import { api, type Relation, type RelatedMemory, type SearchResult } from '../../lib/api'
import { typeLabel, TYPE_COLORS } from '../../lib/labels'
import { useTranslation } from '../../i18n/I18nProvider'
import { useToast } from '../Toast'
import { useDefaultWorkspace } from '../../hooks/useDashboard'
import { TabContentSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import EmptyState from '../EmptyState'
import { Button } from '../ui/Button'

const RELATION_TYPES = ['related', 'supports', 'contradicts', 'supersedes', 'refines'] as const

const FIELD_CLASS =
  'rounded-lg border border-[var(--border-default)] bg-surface-card px-2 py-1.5 text-sm text-[var(--text-primary)] outline-none focus-visible:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-200/30'

interface Props {
  memoryId: string
  onNavigateToMemory?: (memoryId: string) => void
}

export default function MemoryRelationsTab({ memoryId, onNavigateToMemory }: Props) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const { data: workspaceId } = useDefaultWorkspace()

  const [relations, setRelations] = useState<Relation[]>([])
  const [relatedMemories, setRelatedMemories] = useState<RelatedMemory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [creating, setCreating] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [target, setTarget] = useState<SearchResult | null>(null)
  const [relationType, setRelationType] = useState<string>('related')
  const [saving, setSaving] = useState(false)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editType, setEditType] = useState<string>('related')

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

  // 目标记忆搜索：输入 2 个字符后防抖查询，排除自身
  useEffect(() => {
    if (!creating || !workspaceId || query.trim().length < 2) {
      setResults([])
      return
    }
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        const data = await api.hybridSearch(query.trim(), workspaceId, { limit: 8 })
        if (!cancelled) {
          setResults(data.results.filter((item) => item.id !== memoryId).slice(0, 8))
        }
      } catch {
        if (!cancelled) setResults([])
      }
    }, 300)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [creating, workspaceId, query, memoryId])

  const resetCreateForm = () => {
    setCreating(false)
    setQuery('')
    setResults([])
    setTarget(null)
    setRelationType('related')
  }

  const handleCreate = async () => {
    if (!target) return
    setSaving(true)
    try {
      await api.createMemoryRelation(memoryId, target.id, relationType)
      toast(t.memories.relationCreated, 'success')
      resetCreateForm()
      fetchData()
    } catch {
      toast(t.memories.relationCreateFailed, 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (relationId: string) => {
    if (!window.confirm(t.memories.confirmDeleteRelation)) return
    try {
      await api.deleteMemoryRelation(memoryId, relationId)
      toast(t.memories.relationDeleted, 'success')
      fetchData()
    } catch {
      toast(t.memories.relationDeleteFailed, 'error')
    }
  }

  const handleUpdate = async (relationId: string) => {
    try {
      await api.updateMemoryRelation(memoryId, relationId, { relation_type: editType })
      toast(t.memories.relationUpdated, 'success')
      setEditingId(null)
      fetchData()
    } catch {
      toast(t.memories.relationUpdateFailed, 'error')
    }
  }

  const relationLabel = (type: string) => (t.graph.relation as Record<string, string>)[type] ?? type

  if (loading) return <TabContentSkeleton />
  if (error)
    return (
      <ErrorAlert
        message={t.memories.loadRelationsFailed}
        onRetry={fetchData}
        retryLabel={t.common.retry}
      />
    )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-medium text-[var(--text-secondary)]">
          {t.memories.relationType}
        </h4>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => (creating ? resetCreateForm() : setCreating(true))}
        >
          {creating ? t.common.cancel : t.memories.addRelation}
        </Button>
      </div>

      {creating && (
        <div className="space-y-2 rounded-lg border border-[var(--border-default)] bg-surface-inset p-3">
          {!target ? (
            <>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t.memories.selectTargetMemory}
                className={`w-full ${FIELD_CLASS}`}
                aria-label={t.memories.selectTargetMemory}
              />
              {results.length > 0 && (
                <div className="space-y-1">
                  {results.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setTarget(item)}
                      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-brand-badge-bg"
                    >
                      <span
                        className={`shrink-0 rounded-lg border px-1.5 py-0.5 text-sm ${TYPE_COLORS[item.type] || 'border-[var(--border-default)] bg-surface-inset text-[var(--text-secondary)]'}`}
                      >
                        {typeLabel(t.common, item.type)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm text-[var(--text-primary)]">
                        {item.title}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {query.trim().length >= 2 && results.length === 0 && (
                <p className="text-xs text-[var(--text-tertiary)]">{t.memories.noSearchResults}</p>
              )}
            </>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm text-[var(--text-primary)]">
                  {target.title}
                </span>
                <Button size="xs" variant="ghost" onClick={() => setTarget(null)}>
                  {t.common.cancel}
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={relationType}
                  onChange={(e) => setRelationType(e.target.value)}
                  className={FIELD_CLASS}
                  aria-label={t.memories.selectRelationType}
                >
                  {RELATION_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {relationLabel(type)}
                    </option>
                  ))}
                </select>
                <Button size="sm" disabled={saving} onClick={handleCreate}>
                  {t.common.save}
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {relations.length === 0 && relatedMemories.length === 0 && (
        <EmptyState illustration={<EmptyRelations />} message={t.memories.noRelations} />
      )}

      {relations.length > 0 && (
        <div className="space-y-2">
          {relations.map((r) => {
            const otherId =
              r.source_memory_id === memoryId ? r.target_memory_id : r.source_memory_id
            const other = relatedMemories.find((m) => m.id === otherId)
            return (
              <div
                key={r.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border-default)] bg-surface-inset p-2"
              >
                <span className="shrink-0 rounded-lg border border-[var(--glass-border)] bg-surface-card px-1.5 py-0.5 text-sm text-[var(--text-primary)]">
                  {relationLabel(r.relation_type)}
                </span>
                <button
                  type="button"
                  onClick={() => onNavigateToMemory?.(otherId)}
                  className="min-w-0 flex-1 truncate text-left text-sm text-[var(--text-primary)] hover:underline"
                >
                  {other?.title ?? otherId.slice(0, 8)}
                </button>
                <span className="shrink-0 text-xs tabular-nums text-[var(--text-tertiary)]">
                  {Math.round(r.confidence * 100)}%
                </span>
                {editingId === r.id ? (
                  <>
                    <select
                      value={editType}
                      onChange={(e) => setEditType(e.target.value)}
                      className={FIELD_CLASS}
                      aria-label={t.memories.selectRelationType}
                    >
                      {RELATION_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {relationLabel(type)}
                        </option>
                      ))}
                    </select>
                    <Button size="xs" onClick={() => handleUpdate(r.id)}>
                      {t.common.save}
                    </Button>
                    <Button size="xs" variant="ghost" onClick={() => setEditingId(null)}>
                      {t.common.cancel}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => {
                        setEditingId(r.id)
                        setEditType(r.relation_type)
                      }}
                    >
                      {t.memories.editRelation}
                    </Button>
                    <Button size="xs" variant="ghost" onClick={() => handleDelete(r.id)}>
                      {t.memories.deleteRelation}
                    </Button>
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}

      {relatedMemories.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-[var(--text-secondary)]">
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
                className="group relative flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--border-default)] bg-surface-inset p-2 shadow-warm-xs transition-all duration-150 hover:bg-brand-badge-bg active:scale-[0.98]"
              >
                <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-brand-400 opacity-40 transition-opacity duration-150" />
                <span
                  className={`rounded-lg border px-1.5 py-0.5 text-sm ${TYPE_COLORS[m.type] || 'border-[var(--border-default)] bg-surface-inset text-[var(--text-secondary)]'}`}
                >
                  {typeLabel(t.common, m.type)}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-[var(--text-primary)]">
                  {m.title}
                </span>
                <svg
                  className="h-4 w-4 shrink-0 text-[var(--text-tertiary)]"
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
    </div>
  )
}
