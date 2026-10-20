import { useEffect, useMemo, useState } from 'react'
import { Loader2, Search, Sparkles, Trash2 } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { api } from '../../lib/api'
import type { SessionNote } from '../../lib/api'
import { Dialog } from '../ui/Dialog'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Textarea } from '../ui/Textarea'
import { Select } from '../ui/Select'
import MarkdownContent from '../MarkdownContent'
import { useToast } from '../Toast'
import { formatRelativeTime } from '../../lib/format'

const MEMORY_TYPES = [
  'fact',
  'decision',
  'issue',
  'convention',
  'pattern',
  'procedure',
  'feedback',
  'reference',
  'constraint',
  'lesson',
  'rule',
]

interface Props {
  note: SessionNote | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onOrganized: () => void
}

function defaultTitle(content: string): string {
  const first = content
    .split('\n')
    .map((line) => line.replace(/^#+\s*/, '').trim())
    .find(Boolean)
  return (first || '未命名笔记').slice(0, 80)
}

export default function NoteDetailModal({ note, open, onOpenChange, onOrganized }: Props) {
  const { t, locale } = useTranslation()
  const { toast } = useToast()
  const [detail, setDetail] = useState<SessionNote | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [mode, setMode] = useState<'view' | 'organize' | 'merge'>('view')
  const [submitting, setSubmitting] = useState(false)
  const [title, setTitle] = useState('')
  const [type, setType] = useState('fact')
  const [content, setContent] = useState('')
  const [discarding, setDiscarding] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  useEffect(() => {
    if (!open || !note) return
    let cancelled = false
    setLoading(true)
    setLoadError(false)
    setDetail(null)
    setMode('view')
    api
      .getSessionNote(note.id)
      .then((data) => {
        if (cancelled) return
        setDetail(data)
        setTitle(defaultTitle(data.content ?? data.content_preview))
        setContent(data.content ?? data.content_preview)
        setType(data.signal_type === 'issue' ? 'issue' : 'fact')
      })
      .catch(() => {
        if (!cancelled) setLoadError(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, note])

  const fullContent = detail?.content ?? note?.content ?? note?.content_preview ?? ''
  const canOrganize = useMemo(
    () => !!detail && !detail.candidate_id && !detail.formalized,
    [detail],
  )

  // ---- 合并到已有记忆 ----
  const [mergeQuery, setMergeQuery] = useState('')
  const [mergeResults, setMergeResults] = useState<
    { id: string; title: string; content: string; type: string }[]
  >([])
  const [mergeSearching, setMergeSearching] = useState(false)
  const [mergeTarget, setMergeTarget] = useState<{
    id: string
    title: string
    content: string
  } | null>(null)
  const [merging, setMerging] = useState(false)

  useEffect(() => {
    if (mode !== 'merge') return
    setMergeQuery('')
    setMergeResults([])
    setMergeTarget(null)
  }, [mode])

  const searchMergeTargets = async () => {
    const q = mergeQuery.trim()
    if (!detail || q.length < 2) return
    setMergeSearching(true)
    try {
      const res = await api.hybridSearch(q, detail.workspace_id, { limit: 5 })
      setMergeResults(res.results ?? [])
      setMergeTarget(null)
    } catch {
      setMergeResults([])
    } finally {
      setMergeSearching(false)
    }
  }

  const handleMerge = async () => {
    if (!detail || !mergeTarget) return
    setMerging(true)
    try {
      const sep = mergeTarget.content.trimEnd().endsWith('\n') ? '\n' : '\n\n'
      const merged = `${mergeTarget.content.trimEnd()}${sep}\n---\n\n${t.notes.mergeAppend}\n\n${fullContent}\n`
      await api.applyMemoryUpdate(mergeTarget.id, {
        content: merged,
        reason: `merged from note ${detail.id}`,
      })
      await api.formalizeNote(detail.id, { memory_id: mergeTarget.id })
      toast(t.notes.mergeSuccess, 'success')
      onOrganized()
      onOpenChange(false)
    } catch {
      toast(t.notes.mergeFailed, 'error')
    } finally {
      setMerging(false)
    }
  }

  const handleOrganize = async () => {
    if (!detail || !title.trim() || !content.trim()) return
    setSubmitting(true)
    try {
      const created = await api.createCandidate({
        workspace_id: detail.workspace_id,
        title: title.trim(),
        content,
        type,
        source: 'note',
        client_write_id: `note:${detail.id}`,
      })
      await api.formalizeNote(detail.id, { candidate_id: created.candidate.id })
      toast(t.notes.organizeSuccess, 'success')
      onOrganized()
      onOpenChange(false)
    } catch {
      toast(t.notes.organizeFailed, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDiscard = async () => {
    if (!detail) return
    setDiscarding(true)
    try {
      await api.discardNote(detail.id)
      toast(t.notes.discardSuccess, 'success')
      onOrganized()
      onOpenChange(false)
    } catch {
      toast(t.notes.discardFailed, 'error')
    } finally {
      setDiscarding(false)
      setConfirmDiscard(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={
        mode === 'organize'
          ? t.notes.organizeTitle
          : mode === 'merge'
            ? t.notes.mergeTitle
            : t.notes.detailTitle
      }
      description={detail ? `${t.notes.workspace}：${detail.workspace_name ?? '-'}` : undefined}
      size="xl"
      fixedHeight
      footer={
        <div className="flex items-center justify-end gap-2">
          {detail?.candidate_id && (
            <span className="mr-auto text-xs text-[var(--text-tertiary)]">
              {t.notes.candidateLinked}
            </span>
          )}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t.notes.cancel}
          </Button>
          {canOrganize && mode === 'view' && (
            <>
              {confirmDiscard ? (
                <>
                  <span className="mr-auto text-xs text-[var(--text-secondary)]">
                    {t.notes.discardConfirm}
                  </span>
                  <Button variant="ghost" onClick={() => setConfirmDiscard(false)}>
                    {t.notes.cancel}
                  </Button>
                  <Button variant="danger" onClick={handleDiscard} disabled={discarding}>
                    {discarding && <Loader2 size={14} className="mr-1.5 animate-spin" aria-hidden="true" />}
                    {t.notes.discard}
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    variant="ghost"
                    className="text-[var(--text-tertiary)] hover:text-red-500"
                    onClick={() => setConfirmDiscard(true)}
                  >
                    <Trash2 size={14} className="mr-1.5" aria-hidden="true" />
                    {t.notes.discard}
                  </Button>
                  <Button variant="secondary" onClick={() => setMode('merge')}>
                    {t.notes.mergeInto}
                  </Button>
                  <Button onClick={() => setMode('organize')}>
                    <Sparkles size={14} className="mr-1.5" aria-hidden="true" />
                    {t.notes.organize}
                  </Button>
                </>
              )}
            </>
          )}
          {mode === 'organize' && (
            <Button
              onClick={handleOrganize}
              disabled={submitting || !title.trim() || !content.trim()}
            >
              {submitting && (
                <Loader2 size={14} className="mr-1.5 animate-spin" aria-hidden="true" />
              )}
              {submitting ? t.notes.saving : t.notes.save}
            </Button>
          )}
          {mode === 'merge' && (
            <Button onClick={handleMerge} disabled={!mergeTarget || merging}>
              {merging && <Loader2 size={14} className="mr-1.5 animate-spin" aria-hidden="true" />}
              {t.notes.mergeSubmit}
            </Button>
          )}
        </div>
      }
    >
      {loading ? (
        <div className="flex-1 flex items-center justify-center text-[var(--text-tertiary)]">
          <Loader2 size={20} className="animate-spin" aria-hidden="true" />
        </div>
      ) : loadError ? (
        <div className="flex-1 flex items-center justify-center text-sm text-[var(--text-tertiary)]">
          {t.notes.detailLoadFailed}
        </div>
      ) : detail ? (
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin space-y-4 pb-2">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--text-tertiary)]">
            <span>
              {t.notes.host}：{detail.host ?? '-'}
            </span>
            <span>
              {t.notes.workspace}：{detail.workspace_name ?? '-'}
            </span>
            <span>
              {t.notes.length}：{detail.content_length}
            </span>
            <span>
              {t.notes.created}：{formatRelativeTime(detail.created_at, t.common, locale)}
            </span>
          </div>

          {mode === 'organize' ? (
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">
                  {t.notes.titleLabel}
                </label>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80} />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">
                  {t.notes.typeLabel}
                </label>
                <Select
                  value={type}
                  onChange={setType}
                  options={MEMORY_TYPES.map((value) => ({ value, label: value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">
                  {t.notes.contentLabel}
                </label>
                <Textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  className="min-h-[320px] font-mono text-xs"
                />
              </div>
            </div>
          ) : mode === 'merge' ? (
            <div className="space-y-3">
              <div className="flex gap-2">
                <Input
                  value={mergeQuery}
                  onChange={(e) => setMergeQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') searchMergeTargets()
                  }}
                  placeholder={t.notes.mergeSearchPlaceholder}
                />
                <Button variant="secondary" onClick={searchMergeTargets} disabled={mergeSearching}>
                  {mergeSearching ? (
                    <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                  ) : (
                    <Search size={14} aria-hidden="true" />
                  )}
                </Button>
              </div>
              {mergeResults.length > 0 && (
                <div className="space-y-1.5">
                  {mergeResults.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() =>
                        setMergeTarget({
                          id: item.id,
                          title: item.title,
                          content: item.content,
                        })
                      }
                      className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-all ${
                        mergeTarget?.id === item.id
                          ? 'border-brand-400 bg-brand-50/40'
                          : 'border-[var(--border-default)] hover:bg-surface-elevated/40'
                      }`}
                    >
                      <div className="truncate font-medium text-[var(--text-primary)]">
                        {item.title}
                      </div>
                      <div className="truncate text-xs text-[var(--text-tertiary)]">
                        {item.content}
                      </div>
                    </button>
                  ))}
                </div>
              )}
              {mergeQuery.trim().length >= 2 && !mergeSearching && mergeResults.length === 0 && (
                <p className="text-xs text-[var(--text-tertiary)]">{t.notes.mergeNoResults}</p>
              )}
              {mergeTarget && (
                <p className="text-xs text-[var(--text-secondary)]">{t.notes.mergeAppend}</p>
              )}
              {!mergeTarget && mergeResults.length === 0 && (
                <p className="text-xs text-[var(--text-tertiary)]">{t.notes.mergeNoTarget}</p>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-[var(--glass-border)] bg-surface-card/40 p-4">
              <MarkdownContent content={fullContent} />
            </div>
          )}
        </div>
      ) : null}
    </Dialog>
  )
}
