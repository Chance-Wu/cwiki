import { useState } from 'react'
import { EmptyConflict } from '../EmptyIllustrations'
import { useTranslation } from '../../i18n/I18nProvider'
import type { Conflict } from '../../lib/api'
import { formatTimeShort } from '../../lib/format'
import { ListSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import EmptyState from '../EmptyState'
import { Dialog } from '../ui/Dialog'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { Textarea } from '../ui/Textarea'
import { useModal } from '../../hooks/useModal'
import { useToast } from '../Toast'
import { useConflicts, useResolveConflict } from '../../hooks/useConflicts'
import { Card } from '../ui/Card'

export default function ConflictsTab() {
  const { t, locale } = useTranslation()
  const { toast } = useToast()
  const [selectedConflict, setSelectedConflict] = useState<Conflict | null>(null)
  const [resolution, setResolution] = useState('')

  useModal(!!selectedConflict, () => {
    setSelectedConflict(null)
    setResolution('')
  })

  const conflictsQuery = useConflicts()
  const conflicts = conflictsQuery.data ?? []
  const resolveMutation = useResolveConflict()

  const handleResolveConflict = async () => {
    if (!selectedConflict || !resolution.trim()) return
    try {
      await resolveMutation.mutateAsync({ id: selectedConflict.id, resolution: resolution.trim() })
      toast(t.conflicts.resolveConfirm, 'success')
      setSelectedConflict(null)
      setResolution('')
    } catch {
      toast(t.conflicts.resolveFailed, 'error')
    }
  }

  if (conflictsQuery.isLoading) return <ListSkeleton rows={4} />
  if (conflictsQuery.isError)
    return (
      <ErrorAlert
        message={t.conflicts.loadFailed}
        onRetry={() => conflictsQuery.refetch()}
        retryLabel={t.common.retry}
      />
    )
  if (conflicts.length === 0)
    return <EmptyState illustration={<EmptyConflict />} message={t.conflicts.empty} />

  return (
    <>
      <div className="space-y-2">
        {conflicts.map((c, idx) => (
          <Card
            key={c.id}
            onClick={() => {
              setSelectedConflict(c)
              setResolution('')
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                setSelectedConflict(c)
                setResolution('')
              }
            }}
            role="button"
            tabIndex={0}
            className={`group relative px-4 py-3 stagger-item stagger-${Math.min(idx + 1, 8)} transition-all duration-150 select-none cursor-pointer hover-lift hover:bg-danger/5 active:scale-[0.98]`}
          >
            <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-full bg-danger opacity-40 transition-opacity duration-150" />
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant={c.status === 'open' ? 'danger' : 'success'}>{c.status}</Badge>
                  <span className="text-sm text-[var(--text-secondary)]">{c.conflict_type}</span>
                  <span className="text-sm text-[var(--text-tertiary)] ml-auto">
                    {formatTimeShort(c.created_at, locale)}
                  </span>
                </div>
                {c.description && (
                  <p className="text-sm text-[var(--text-secondary)] mt-1 break-words">
                    {c.description}
                  </p>
                )}
                <div className="flex flex-wrap gap-3 mt-1.5 text-sm text-[var(--text-tertiary)]">
                  <span>
                    {t.conflicts.memoryId}:{' '}
                    <span className="font-mono tabular-nums bg-surface-inset border border-[var(--border-default)] shadow-warm-xs px-1 py-0.5 rounded-lg text-xs">
                      {c.memory_id.slice(0, 8)}
                    </span>
                    ...
                  </span>
                  {c.candidate_id && (
                    <span>
                      {t.conflicts.candidateId}:{' '}
                      <span className="font-mono tabular-nums bg-surface-inset border border-[var(--border-default)] shadow-warm-xs px-1 py-0.5 rounded-lg text-xs">
                        {c.candidate_id.slice(0, 8)}
                      </span>
                      ...
                    </span>
                  )}
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Dialog
        open={!!selectedConflict}
        onOpenChange={(o) => {
          if (!o) {
            setSelectedConflict(null)
            setResolution('')
          }
        }}
        title={selectedConflict ? `${t.conflicts.type}: ${selectedConflict.conflict_type}` : ''}
        size="lg"
        fixedHeight
        footer={
          selectedConflict && selectedConflict.status === 'open' ? (
            <div className="flex flex-col gap-2">
              <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
                {t.conflicts.resolution}
              </label>
              <Textarea
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
                placeholder={t.conflicts.resolvePlaceholder}
                rows={3}
              />
              <Button
                onClick={handleResolveConflict}
                disabled={!resolution.trim() || resolveMutation.isPending}
              >
                {resolveMutation.isPending ? t.common.loading : t.conflicts.resolve}
              </Button>
            </div>
          ) : undefined
        }
      >
        {selectedConflict && (
          <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
            <div className="space-y-2 text-base">
              <div>
                <span className="text-[var(--text-secondary)]">{t.conflicts.status}: </span>
                <Badge variant={selectedConflict.status === 'open' ? 'danger' : 'success'}>
                  {selectedConflict.status}
                </Badge>
              </div>
              {selectedConflict.description && (
                <div>
                  <span className="text-[var(--text-secondary)]">{t.conflicts.description}: </span>
                  <p className="text-[var(--text-secondary)] mt-1">
                    {selectedConflict.description}
                  </p>
                </div>
              )}
              <div>
                <span className="text-[var(--text-secondary)]">{t.conflicts.memoryId}: </span>
                <span className="font-mono text-sm bg-surface-inset border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 rounded-lg">
                  {selectedConflict.memory_id}
                </span>
              </div>
              {selectedConflict.candidate_id && (
                <div>
                  <span className="text-[var(--text-secondary)]">{t.conflicts.candidateId}: </span>
                  <span className="font-mono text-sm bg-surface-inset border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 rounded-lg">
                    {selectedConflict.candidate_id}
                  </span>
                </div>
              )}
              <div>
                <span className="text-[var(--text-secondary)]">{t.conflicts.createdAt}: </span>
                <span>{formatTimeShort(selectedConflict.created_at, locale)}</span>
              </div>
              {selectedConflict.resolution && (
                <div>
                  <span className="text-[var(--text-secondary)]">{t.conflicts.resolution}: </span>
                  <p className="text-[var(--text-primary)] mt-1">{selectedConflict.resolution}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </Dialog>
    </>
  )
}
