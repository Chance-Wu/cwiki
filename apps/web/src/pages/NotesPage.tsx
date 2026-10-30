import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, Inbox } from 'lucide-react'
import { useTranslation } from '../i18n/I18nProvider'
import { api } from '../lib/api'
import type { SessionNote } from '../lib/api'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import { Card } from '../components/ui/Card'
import { Select } from '../components/ui/Select'
import Pagination from '../components/Pagination'
import ErrorAlert from '../components/ErrorAlert'
import EmptyState from '../components/EmptyState'
import { EmptyInbox } from '../components/EmptyIllustrations'
import { ListSkeleton } from '../components/Skeleton'
import { useWorkspaces } from '../hooks/useCandidates'
import { formatRelativeTime } from '../lib/format'
import NoteDetailModal from '../components/notes/NoteDetailModal'

const PAGE_SIZE = 12

export default function NotesPage() {
  const { t, locale } = useTranslation()
  const [workspaceId, setWorkspaceId] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<SessionNote | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

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

  const openNote = (note: SessionNote) => {
    setSelected(note)
    setModalOpen(true)
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
          <div className="space-y-3">
            {notes.map((note) => (
              <Card
                key={note.id}
                className="p-4 md:p-5 cursor-pointer transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)]"
                onClick={() => openNote(note)}
              >
                <div className="flex items-start gap-3">
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
