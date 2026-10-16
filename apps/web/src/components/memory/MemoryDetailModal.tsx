import { useState, useCallback, lazy, Suspense } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { api, type FileMemory } from '../../lib/api'
import { typeLabel, sourceLabel, SOURCE_COLORS, TYPE_COLORS } from '../../lib/labels'
import { ensureUtc } from '../../lib/format'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { Input } from '../ui/Input'
import { Textarea } from '../ui/Textarea'
import { Badge } from '../ui/Badge'
import { Tabs, TabsList, TabsTrigger, AnimatedTabsContent } from '../ui/Tabs'
import MarkdownContent from '../MarkdownContent'
import { useToast } from '../Toast'
import MemoryEvidenceSection from './MemoryEvidenceSection'

const MemoryVersionsTab = lazy(() => import('./MemoryVersionsTab'))
const MemoryFeedbackTab = lazy(() => import('./MemoryFeedbackTab'))
const MemoryRetrievalTab = lazy(() => import('./MemoryRetrievalTab'))
const MemoryLifecycleTab = lazy(() => import('./MemoryLifecycleTab'))
const MemoryRelationsTab = lazy(() => import('./MemoryRelationsTab'))
const MemoryHealthTab = lazy(() => import('./MemoryHealthTab'))

const TabFallback = () => (
  <div className="flex items-center justify-center py-12 text-[var(--text-tertiary)] text-sm">
    <Loader2 size={14} className="animate-spin mr-2" aria-hidden="true" />
  </div>
)

type DetailTab =
  'content' | 'versions' | 'feedback' | 'retrieval' | 'lifecycle' | 'relations' | 'health'

export interface OptimizePreview {
  memoryId: string
  originalTitle: string
  originalContent: string
  optimizedTitle: string
  optimizedContent: string
  changes: string
}

function getFreshness(memory: FileMemory): 'fresh' | 'aging' | 'stale' {
  const type = memory.type || 'fact'
  const thresholds: Record<string, { fresh: number; aging: number }> = {
    fact: { fresh: 30, aging: 90 },
    reference: { fresh: 30, aging: 90 },
    decision: { fresh: 60, aging: 180 },
    convention: { fresh: 60, aging: 180 },
    pattern: { fresh: 60, aging: 180 },
    issue: { fresh: 30, aging: 90 },
    procedure: { fresh: 30, aging: 90 },
    feedback: { fresh: 30, aging: 90 },
  }
  const t = thresholds[type] || thresholds.fact
  const dateStr = memory.last_used_at || memory.updated_at
  if (!dateStr) return 'stale'
  const days = (Date.now() - new Date(ensureUtc(dateStr)).getTime()) / 86400000
  if (days < t.fresh) return 'fresh'
  if (days < t.aging) return 'aging'
  return 'stale'
}

interface MemoryDetailModalProps {
  memory: FileMemory | null
  onClose: () => void
  onMemoryUpdated: () => void
  onNavigateToMemory?: (memoryId: string) => void
}

export default function MemoryDetailModal({
  memory,
  onClose,
  onMemoryUpdated,
  onNavigateToMemory,
}: MemoryDetailModalProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [detailTab, setDetailTab] = useState<DetailTab>('content')
  const [editing, setEditing] = useState(false)
  const [editTab, setEditTab] = useState<'source' | 'preview'>('source')
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleStartEdit = useCallback(() => {
    if (!memory) return
    setEditTitle(memory.title)
    setEditContent(memory.content)
    setEditTab('source')
    setEditing(true)
  }, [memory])

  const handleSaveEdit = useCallback(async () => {
    if (!memory) return
    setSaving(true)
    try {
      await api.updateMemory(memory.id, { title: editTitle, content: editContent })
      setEditing(false)
      toast(t.memories.saveSuccess, 'success')
      onMemoryUpdated()
    } catch {
      toast(t.memories.saveFailed, 'error')
    } finally {
      setSaving(false)
    }
  }, [
    memory,
    editTitle,
    editContent,
    toast,
    t.memories.saveSuccess,
    t.memories.saveFailed,
    onMemoryUpdated,
  ])

  const handleDelete = useCallback(async () => {
    if (!memory) return
    setDeleting(true)
    try {
      await api.deleteMemory(memory.id)
      toast(t.memories.deleteSuccess, 'success')
      onClose()
      onMemoryUpdated()
    } catch {
      toast(t.memories.deleteFailed, 'error')
    } finally {
      setDeleting(false)
    }
  }, [memory, toast, t.memories.deleteSuccess, t.memories.deleteFailed, onClose, onMemoryUpdated])

  const handleClose = useCallback(() => {
    onClose()
    setEditing(false)
    setConfirmDelete(false)
    setDetailTab('content')
  }, [onClose])

  if (!memory) return null

  const freshness = getFreshness(memory)
  const freshnessColor =
    freshness === 'fresh' ? 'bg-success' : freshness === 'aging' ? 'bg-warning' : 'bg-danger'
  const freshnessLabel =
    freshness === 'fresh'
      ? t.memories.fresh
      : freshness === 'aging'
        ? t.memories.aging
        : t.memories.stale
  const statusKey = memory.status || 'active'
  const statusLbl =
    statusKey === 'archived'
      ? t.memories.statusArchived
      : statusKey === 'deprecated'
        ? t.memories.statusDeprecated
        : t.memories.statusActive
  const statusVariant =
    statusKey === 'archived'
      ? ('default' as const)
      : statusKey === 'deprecated'
        ? ('warning' as const)
        : ('success' as const)

  const tabs: [DetailTab, string][] = [
    ['content', t.memories.contentTab],
    ['versions', t.memories.versions],
    ['feedback', t.memories.feedback],
    ['retrieval', t.memoryDetail.retrievalTab],
    ['lifecycle', t.memories.lifecycle],
    ['relations', t.memories.relations],
    ['health', t.memories.health],
  ]

  const tabContentClass = 'pt-4 pb-4'

  return (
    <Dialog
      open={!!memory}
      onOpenChange={(o) => {
        if (!o) handleClose()
      }}
      title={editing ? t.common.edit : memory.title}
      size="xl"
      fixedHeight
      titleLayoutId={editing ? undefined : `mem-title-${memory.id}`}
      footer={
        detailTab === 'content' ? (
          <div className="flex justify-between items-center">
            {editing ? (
              <>
                <div />
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setEditing(false)} disabled={saving}>
                    {t.common.cancel}
                  </Button>
                  <Button
                    onClick={handleSaveEdit}
                    disabled={saving || !editTitle.trim() || !editContent.trim()}
                  >
                    {saving ? (
                      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                    ) : null}
                    {saving ? t.memories.saving : t.common.save}
                  </Button>
                </div>
              </>
            ) : confirmDelete ? (
              <>
                <span className="text-sm text-danger-fg">{t.memories.deleteConfirm}</span>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => setConfirmDelete(false)}
                    disabled={deleting}
                  >
                    {t.common.cancel}
                  </Button>
                  <Button variant="danger" onClick={handleDelete} disabled={deleting}>
                    {deleting ? (
                      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                    ) : null}
                    {deleting ? t.memories.deleting : t.common.confirm}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <Button variant="ghost" onClick={() => setConfirmDelete(true)}>
                  {t.common.delete}
                </Button>
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={handleStartEdit}>
                    {t.common.edit}
                  </Button>
                </div>
              </>
            )}
          </div>
        ) : undefined
      }
    >
      <div className="mb-4">
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          {memory.is_permanent && (
            <span
              className="flex items-center gap-1 text-warning-fg mr-1"
              title={t.memories.permanentMark}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="currentColor"
                aria-hidden="true"
              >
                <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
              </svg>
              <span className="text-warning-fg font-medium text-xs">
                {t.memories.permanentMark}
              </span>
            </span>
          )}
          <Badge className={TYPE_COLORS[memory.type] || ''}>
            {typeLabel(t.common, memory.type)}
          </Badge>
          <Badge className={SOURCE_COLORS[memory.source || ''] || ''}>
            {sourceLabel(t.common, memory.source || '')}
          </Badge>
          <Badge variant={statusVariant}>{statusLbl}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--text-tertiary)]">
          <span className="flex items-center gap-1.5" title={freshnessLabel}>
            <span className={`w-1.5 h-1.5 rounded-full ${freshnessColor}`} />
            <span className="font-medium">{freshnessLabel}</span>
          </span>
          {memory.file_path && (
            <span
              className="font-mono text-[var(--text-secondary)] bg-surface-inset border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 rounded-lg"
              title={memory.file_path}
            >
              {memory.file_path}
            </span>
          )}
          {memory.version && <span className="tabular-nums">v{memory.version}</span>}
          {memory.confidence != null && (
            <span className="tabular-nums">
              {t.memories.confidence} {Math.round(memory.confidence * 100)}%
            </span>
          )}
        </div>
      </div>

      <Tabs
        value={detailTab}
        onValueChange={(v) => setDetailTab(v as DetailTab)}
        defaultValue="content"
        className="flex-1 min-h-0 flex flex-col"
      >
        <TabsList>
          {tabs.map(([tab, label]) => (
            <TabsTrigger key={tab} value={tab} className="whitespace-nowrap shrink-0">
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <AnimatedTabsContent value="content" className={tabContentClass}>
          {editing ? (
            <>
              <Input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                className="mb-3 text-lg font-semibold"
              />
              <div className="flex gap-1 mb-3">
                <button
                  role="tab"
                  aria-selected={editTab === 'source'}
                  onClick={() => setEditTab('source')}
                  className={`px-3 py-1 text-sm rounded-lg transition-all duration-150 select-none active:scale-[0.97] ${editTab === 'source' ? 'bg-surface-inset text-[var(--text-primary)] font-medium' : 'text-[var(--text-secondary)] hover:bg-surface-inset'}`}
                >
                  {t.memories.sourceTab}
                </button>
                <button
                  role="tab"
                  aria-selected={editTab === 'preview'}
                  onClick={() => setEditTab('preview')}
                  className={`px-3 py-1 text-sm rounded-lg transition-all duration-150 select-none active:scale-[0.97] ${editTab === 'preview' ? 'bg-surface-inset text-[var(--text-primary)] font-medium' : 'text-[var(--text-secondary)] hover:bg-surface-inset'}`}
                >
                  {t.memories.previewTab}
                </button>
              </div>
              {editTab === 'source' ? (
                <Textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  rows={12}
                  className="font-mono"
                />
              ) : (
                <div className="p-4 min-h-[280px] bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs">
                  <MarkdownContent content={editContent} />
                </div>
              )}
            </>
          ) : (
            <MarkdownContent content={memory.content} />
          )}
          {/* 编辑态不渲染证据区，避免打断源码编辑 */}
          {!editing && <MemoryEvidenceSection memoryId={memory.id} />}
        </AnimatedTabsContent>

        <AnimatedTabsContent value="versions" className={tabContentClass}>
          <Suspense fallback={<TabFallback />}>
            <MemoryVersionsTab memoryId={memory.id} />
          </Suspense>
        </AnimatedTabsContent>

        <AnimatedTabsContent value="feedback" className={tabContentClass}>
          <Suspense fallback={<TabFallback />}>
            <MemoryFeedbackTab memoryId={memory.id} />
          </Suspense>
        </AnimatedTabsContent>

        <AnimatedTabsContent value="retrieval" className={tabContentClass}>
          <Suspense fallback={<TabFallback />}>
            <MemoryRetrievalTab memoryId={memory.id} />
          </Suspense>
        </AnimatedTabsContent>

        <AnimatedTabsContent value="lifecycle" className={tabContentClass}>
          <Suspense fallback={<TabFallback />}>
            <MemoryLifecycleTab memoryId={memory.id} />
          </Suspense>
        </AnimatedTabsContent>

        <AnimatedTabsContent value="relations" className={tabContentClass}>
          <Suspense fallback={<TabFallback />}>
            <MemoryRelationsTab memoryId={memory.id} onNavigateToMemory={onNavigateToMemory} />
          </Suspense>
        </AnimatedTabsContent>

        <AnimatedTabsContent value="health" className={tabContentClass}>
          <Suspense fallback={<TabFallback />}>
            <MemoryHealthTab memoryId={memory.id} />
          </Suspense>
        </AnimatedTabsContent>
      </Tabs>
    </Dialog>
  )
}
