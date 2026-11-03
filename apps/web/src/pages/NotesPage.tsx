import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Inbox, Loader2, Trash2 } from 'lucide-react'
import { useTranslation, translate } from '../i18n/I18nProvider'
import { api } from '../lib/api'
import type { SessionNote } from '../lib/api'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import { Card } from '../components/ui/Card'
import { Select } from '../components/ui/Select'
import { Checkbox } from '../components/ui/Checkbox'
import { Button } from '../components/ui/Button'
import { useToast } from '../components/Toast'
import Pagination from '../components/Pagination'
import ErrorAlert from '../components/ErrorAlert'
import EmptyState from '../components/EmptyState'
import { EmptyInbox } from '../components/EmptyIllustrations'
import { ListSkeleton } from '../components/Skeleton'
import { useWorkspaces } from '../hooks/useCandidates'
import { useBatchSelection } from '../hooks/useBatchSelection'
import { formatRelativeTime } from '../lib/format'
import NoteDetailModal from '../components/notes/NoteDetailModal'

const PAGE_SIZE = 12

export default function NotesPage() {
  const { t, locale } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [workspaceId, setWorkspaceId] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<SessionNote | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  const workspacesQuery = useWorkspaces()
  const workspaces = workspacesQuery.data ?? []

  const notesQuery = useQuery({
    queryKey: ['session-notes', workspaceId, page],
    queryFn: () =>
      api.getSessionNotes({
        workspaceId: workspaceId || undefined,
        formalized: false,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
  })

  const notes = useMemo(() => notesQuery.data?.items ?? [], [notesQuery.data])
  const total = notesQuery.data?.total ?? 0
  const noteIds = useMemo(() => notes.map((note) => note.id), [notes])
  const { selectedIds, toggleSelect, toggleSelectAll, clearSelection } = useBatchSelection(noteIds)

  const openNote = (note: SessionNote) => {
    setSelected(note)
    setModalOpen(true)
  }

  const handleBatchDiscard = async () => {
    if (selectedIds.size === 0) return
    setDiscarding(true)
    try {
      const { discarded } = await api.batchDiscardNotes(Array.from(selectedIds))
      toast(translate(t.notes.batchDiscardSuccess, { n: discarded }), 'success')
      await queryClient.invalidateQueries({ queryKey: ['session-notes'] })
      clearSelection()
      setConfirmDiscard(false)
    } catch {
      toast(t.notes.discardFailed, 'error')
    } finally {
      setDiscarding(false)
    }
  }

  return (
    <PageShell
      header={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <PageTitle icon={<FileText size={18} />} title={t.notes.title} />
          <div className="w-56">
            <Select
              value={workspaceId}
              onChange={(value) => {
                setWorkspaceId(value)
                setPage(1)
              }}
              options={[
                { value: '', label: t.notes.allWorkspaces },
                ...workspaces.map((ws) => ({ value: ws.id, label: ws.name })),
              ]}
            />
          </div>
        </div>
      }
    >
      {notesQuery.isLoading ? (
        <ListSkeleton rows={5} />
      ) : notesQuery.isError ? (
        <ErrorAlert
          message={t.notes.loadFailed}
          onRetry={() => notesQuery.refetch()}
          retryLabel={t.common.retry}
        />
      ) : notes.length === 0 ? (
        <EmptyState
          illustration={<EmptyInbox />}
          message={t.notes.empty}
          description={t.notes.emptyHint}
        />
      ) : (
        <>
          <div className="flex items-center justify-between gap-3 mb-2 px-1">
            <div className="flex items-center gap-2">
              <Checkbox
                checked={selectedIds.size === notes.length && notes.length > 0}
                onCheckedChange={toggleSelectAll}
              />
              <span className="text-sm text-[var(--text-secondary)]">{t.notes.selectAll}</span>
            </div>
          </div>

          {selectedIds.size > 0 && (
            <div className="mb-3 flex items-center justify-between gap-3 px-4 py-3 glass rounded-xl">
              <span className="text-sm text-[var(--text-secondary)]">
                {translate(t.notes.selectedCount, { n: selectedIds.size })}
              </span>
              {confirmDiscard ? (
                <div className="flex items-center gap-3">
                  <span className="text-sm text-[var(--text-secondary)]">
                    {translate(t.notes.confirmBatchDiscard, { n: selectedIds.size })}
                  </span>
                  <Button variant="secondary" size="sm" onClick={() => setConfirmDiscard(false)}>
                    {t.common.cancel}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={handleBatchDiscard}
                    disabled={discarding}
                  >
                    {discarding && (
                      <Loader2 size={14} className="mr-1.5 animate-spin" aria-hidden="true" />
                    )}
                    {t.notes.discard}
                  </Button>
                </div>
              ) : (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => setConfirmDiscard(true)}
                  disabled={discarding}
                >
                  <Trash2 size={14} className="mr-1.5" aria-hidden="true" />
                  {t.notes.batchDiscard}
                </Button>
              )}
            </div>
          )}

          <div className="space-y-3">
            {notes.map((note) => (
              <Card
                key={note.id}
                className="p-4 md:p-5 cursor-pointer transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)]"
                onClick={() => openNote(note)}
              >
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={selectedIds.has(note.id)}
                      onCheckedChange={() => toggleSelect(note.id)}
                    />
                  </span>
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-fg">
                    {note.candidate_id ? (
                      <Inbox size={15} aria-hidden="true" />
                    ) : (
                      <FileText size={15} aria-hidden="true" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-sm text-[var(--text-primary)]">
                      {note.content_preview}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--text-tertiary)]">
                      <span>{note.host ?? '-'}</span>
                      <span>{note.workspace_name ?? '-'}</span>
                      <span>
                        {t.notes.length}：{note.content_length}
                      </span>
                      <span>{formatRelativeTime(note.created_at, t.common, locale)}</span>
                      {note.candidate_id && (
                        <span className="rounded-full bg-brand-50 px-2 py-0.5 text-brand-fg">
                          {t.notes.candidateLinked}
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="ml-2 shrink-0 text-xs text-[var(--text-tertiary)]">
                    {t.notes.view}
                  </span>
                </div>
              </Card>
            ))}
          </div>
          <Pagination
            page={page}
            total={total}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
            onPageSizeChange={() => undefined}
            pageSizeOptions={[PAGE_SIZE]}
          />
        </>
      )}

      <NoteDetailModal
        note={selected}
        open={modalOpen}
        onOpenChange={setModalOpen}
        onOrganized={() => {
          notesQuery.refetch()
        }}
      />
    </PageShell>
  )
}
