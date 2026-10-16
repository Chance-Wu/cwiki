import { useState, useEffect, useMemo, useCallback, lazy, Suspense, useDeferredValue } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Loader2, Search, Globe, Tag, X, Inbox, Undo2 } from 'lucide-react'
import { useTranslation, translate } from '../i18n/I18nProvider'
import { type Candidate, type FileMemory, api } from '../lib/api'
import { ListSkeleton } from '../components/Skeleton'
import Pagination from '../components/Pagination'
import ErrorAlert from '../components/ErrorAlert'
import EmptyState from '../components/EmptyState'
import { EmptyInbox } from '../components/EmptyIllustrations'
import { useToast } from '../components/Toast'
import { Dialog } from '../components/ui/Dialog'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import { Button } from '../components/ui/Button'
import { Select } from '../components/ui/Select'
import { Card } from '../components/ui/Card'
import { Checkbox } from '../components/ui/Checkbox'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import CandidateItem from '../components/inbox/CandidateItem'
import CandidateQualityCard from '../components/memory/CandidateQualityCard'
const ConflictsTab = lazy(() => import('../components/inbox/ConflictsTab'))
const MemoryDetailModal = lazy(() => import('../components/memory/MemoryDetailModal'))
const CandidateDetailModal = lazy(() => import('../components/inbox/CandidateDetailModal'))
const CandidateEditModal = lazy(() => import('../components/inbox/CandidateEditModal'))
const CandidateMergeModal = lazy(() => import('../components/inbox/CandidateMergeModal'))
import { spring, duration } from '../lib/motion'
import {
  useCandidates,
  useReviewCandidate,
  useBatchReviewCandidate,
  useRevertAutoApprove,
  useWorkspaces,
} from '../hooks/useCandidates'
import { useConflicts } from '../hooks/useConflicts'
import { useBatchSelection } from '../hooks/useBatchSelection'
import { useListKeyboardNav } from '../hooks/useListKeyboardNav'

type InboxTab = 'candidates' | 'approved' | 'conflicts'

export default function InboxPage() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab: InboxTab =
    searchParams.get('tab') === 'conflicts'
      ? 'conflicts'
      : searchParams.get('tab') === 'approved'
        ? 'approved'
        : 'candidates'
  const setActiveTab = (tab: InboxTab) => {
    setSearchParams(tab === 'candidates' ? {} : { tab }, { replace: true })
  }
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState('')
  const [titleSearch, setTitleSearch] = useState('')
  const deferredTitle = useDeferredValue(titleSearch)

  const [detailCandidate, setDetailCandidate] = useState<Candidate | null>(null)
  const [detailMemory, setDetailMemory] = useState<FileMemory | null>(null)
  const [editCandidate, setEditCandidate] = useState<Candidate | null>(null)
  const [mergeCandidate, setMergeCandidate] = useState<Candidate | null>(null)

  const [batchActionLoading, setBatchActionLoading] = useState<string | null>(null)
  const [batchConfirmAction, setBatchConfirmAction] = useState<string | null>(null)
  const [navigatedCandidateId, setNavigatedCandidateId] = useState<string | null>(null)
  const [pendingAutoAdvance, setPendingAutoAdvance] = useState(false)
  // 撤销 auto-approve 的目标候选，非空时显示确认对话框
  const [revertTarget, setRevertTarget] = useState<Candidate | null>(null)

  const conflictsQuery = useConflicts()
  const conflicts = conflictsQuery.data ?? []

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const workspacesQuery = useWorkspaces()
  const workspaces = workspacesQuery.data ?? []

  const queryOpts = useMemo(
    () => ({
      workspaceId: workspaceId || undefined,
      type: typeFilter || undefined,
      title: deferredTitle || undefined,
      // 已生效 tab 查看自动/人工批准的候选，其余查看待审核
      status: activeTab === 'approved' ? 'approved' : 'pending_review',
      limit: pageSize,
      offset: (page - 1) * pageSize,
    }),
    [workspaceId, typeFilter, deferredTitle, activeTab, page, pageSize],
  )

  const candidatesQuery = useCandidates(queryOpts)
  const candidates = useMemo(() => candidatesQuery.data?.items ?? [], [candidatesQuery.data])
  const total = candidatesQuery.data?.total ?? 0
  const pendingTotal = total

  const candidateIds = useMemo(() => candidates.map((c) => c.id), [candidates])
  const { selectedIds, toggleSelect, toggleSelectAll, clearSelection, removeSelected } =
    useBatchSelection(candidateIds)

  useEffect(() => {
    if (candidates.length === 0 && page > 1 && !candidatesQuery.isLoading) {
      setPage(page - 1)
    }
  }, [candidates.length, page, candidatesQuery.isLoading])

  const reviewMutation = useReviewCandidate()
  const actionLoading = reviewMutation.isPending
    ? (reviewMutation.variables?.candidateId ?? null)
    : null

  const revertMutation = useRevertAutoApprove()
  const revertPending = revertMutation.isPending

  // 撤销 auto-approve：成功后候选列表已由 mutation invalidate，这里只负责提示与关框；
  // 后端 404 覆盖「候选不存在」与「无 auto_approve 审核记录」两种情况
  const handleRevertConfirm = async () => {
    if (!revertTarget) return
    try {
      await revertMutation.mutateAsync(revertTarget.id)
      toast(t.inbox.revertSuccess, 'success')
      setRevertTarget(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      if (message.includes('404') || /not found/i.test(message)) {
        toast(t.inbox.revertNotFound, 'warning')
      } else {
        toast(t.inbox.revertFailed, 'error')
      }
    }
  }

  const modalOpen = !!(detailCandidate || detailMemory || editCandidate || mergeCandidate)

  const handleNavSelect = useCallback(
    (idx: number) => toggleSelect(candidates[idx].id),
    [candidates, toggleSelect],
  )
  const handleNavOpen = useCallback(
    (idx: number) => setDetailCandidate(candidates[idx]),
    [candidates],
  )

  const { focusedIndex, setFocusedIndex } = useListKeyboardNav({
    itemCount: candidates.length,
    indexAttr: 'candidate-index',
    onSelect: handleNavSelect,
    onOpen: handleNavOpen,
    disabled: modalOpen,
  })

  useEffect(() => {
    setPage(1)
    setFocusedIndex(-1)
  }, [workspaceId, typeFilter, deferredTitle]) // eslint-disable-line react-hooks/exhaustive-deps

  // 切换 tab 时清空批量选择，避免跨状态残留勾选（已生效 tab 不支持批量操作）
  useEffect(() => {
    clearSelection()
    setBatchConfirmAction(null)
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  // 从首页带 ?id= 跳入时自动打开对应候选详情，随后清掉参数避免刷新重复打开
  const targetId = searchParams.get('id') ?? null
  useEffect(() => {
    if (!targetId || candidates.length === 0) return
    const target = candidates.find((c) => c.id === targetId)
    if (target) {
      setDetailCandidate(target)
      setNavigatedCandidateId(targetId)
      const next = new URLSearchParams(searchParams)
      next.delete('id')
      setSearchParams(next, { replace: true })
    }
  }, [targetId, candidates]) // eslint-disable-line react-hooks/exhaustive-deps

  // 自动推进：审完跳转来源的候选后，自动打开列表中下一条，形成连续审阅流
  useEffect(() => {
    if (!pendingAutoAdvance || candidates.length === 0) return
    setPendingAutoAdvance(false)
    const idx = navigatedCandidateId
      ? candidates.findIndex((c) => c.id === navigatedCandidateId)
      : -1
    const nextCandidate = candidates[idx >= 0 ? idx : 0]
    if (nextCandidate) {
      setDetailCandidate(nextCandidate)
      setNavigatedCandidateId(nextCandidate.id)
    } else {
      setNavigatedCandidateId(null)
    }
  }, [pendingAutoAdvance, candidates]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleReview = async (candidateId: string, action: string) => {
    const shouldAdvance = navigatedCandidateId === candidateId
    try {
      await reviewMutation.mutateAsync({ candidateId, action })
      removeSelected(candidateId)
      if (shouldAdvance && (action === 'approve' || action === 'reject')) {
        setDetailCandidate(null)
        setPendingAutoAdvance(true)
      }
    } catch {
      toast(t.inbox.reviewFailed, 'error')
    }
  }

  const openDetail = useCallback((c: Candidate) => {
    setDetailCandidate(c)
  }, [])

  const batchReviewMutation = useBatchReviewCandidate()

  const handleBatchAction = async (action: string) => {
    if (selectedIds.size === 0) return
    setBatchActionLoading(action)
    try {
      const result = await batchReviewMutation.mutateAsync({
        items: Array.from(selectedIds),
        action,
      })
      clearSelection()
      setBatchConfirmAction(null)
      if (result.failed > 0) {
        toast(
          translate(t.inbox.batchPartialSuccess, {
            success: result.succeeded,
            failed: result.failed,
          }),
          'error',
        )
      }
    } catch {
      toast(t.inbox.batchAllFailed, 'error')
    } finally {
      setBatchActionLoading(null)
    }
  }

  const handleEditSubmit = async (candidate: Candidate, title: string, content: string) => {
    try {
      await reviewMutation.mutateAsync({
        candidateId: candidate.id,
        action: 'edit',
        body: { edited_title: title, edited_content: content },
      })
      setEditCandidate(null)
    } catch {
      toast(t.inbox.editFailed, 'error')
    }
  }

  const handleUpdate = async (candidate: Candidate) => {
    try {
      await reviewMutation.mutateAsync({
        candidateId: candidate.id,
        action: 'update',
        body: { merge_target_memory_id: candidate.similar_memory_id },
      })
    } catch {
      toast(t.inbox.reviewFailed, 'error')
    }
  }

  const loading = candidatesQuery.isLoading
  const error = candidatesQuery.isError ? t.inbox.loadFailed : null

  // 搜索与筛选行：待审 / 已生效两个 tab 复用
  const filterSection = (
    <div className="mb-5">
      {/* 搜索与筛选行 */}
      <div className="flex flex-col sm:flex-row gap-2.5">
        {/* 搜索输入框 */}
        <div className="relative flex-1 min-w-0">
          <div className="relative flex h-9 items-center rounded-lg border border-[var(--glass-border)] bg-surface-card/80 backdrop-blur-[var(--glass-blur)] shadow-warm-sm transition-[border-color,box-shadow] duration-200 ease-out hover:border-[var(--glass-border-hover)] hover:bg-surface-card hover:shadow-warm-md focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-200/30">
            <Search
              size={14}
              strokeWidth={1.75}
              className="pointer-events-none absolute left-2.5 text-[var(--text-tertiary)]"
              aria-hidden="true"
            />
            <input
              type="text"
              value={titleSearch}
              onChange={(e) => setTitleSearch(e.target.value)}
              placeholder={t.inbox.searchTitle}
              aria-label={t.inbox.searchTitle}
              className="h-full w-full bg-transparent pl-8 pr-9 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
            />
            {titleSearch && (
              <button
                onClick={() => setTitleSearch('')}
                className="absolute right-2.5 rounded p-0.5 text-[var(--text-tertiary)] transition-all duration-150 hover:bg-surface-inset hover:text-[var(--text-secondary)] active:scale-95 select-none"
                aria-label={t.common.close}
              >
                <X size={13} strokeWidth={1.75} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>

        {/* 筛选下拉 */}
        <div className="flex gap-2 sm:w-auto">
          <Select
            options={[
              { value: '', label: t.inbox.workspaceAll },
              ...workspaces.map((w) => ({ value: w.id, label: w.name })),
            ]}
            value={workspaceId ?? ''}
            onChange={(v) => setWorkspaceId(v || null)}
            placeholder={t.inbox.workspaceAll}
            icon={<Globe size={14} />}
          />
          <Select
            options={[
              { value: '', label: t.inbox.typeAll },
              { value: 'fact', label: t.memories.typeFact },
              { value: 'decision', label: t.memories.typeDecision },
              { value: 'issue', label: t.memories.typeIssue },
              { value: 'convention', label: t.memories.typeConvention },
              { value: 'pattern', label: t.memories.typePattern },
              { value: 'procedure', label: t.memories.typeProcedure },
              { value: 'feedback', label: t.memories.typeFeedback },
              { value: 'reference', label: t.memories.typeReference },
              { value: 'constraint', label: t.memories.typeConstraint },
              { value: 'lesson', label: t.memories.typeLesson },
              { value: 'rule', label: t.memories.typeRule },
            ]}
            value={typeFilter}
            onChange={setTypeFilter}
            placeholder={t.inbox.typeAll}
            icon={<Tag size={14} />}
          />
        </div>
      </div>
    </div>
  )

  // 列表主体：withBatch 控制批量选择（待审 tab）；已生效 tab 关闭批量、每行显示撤销按钮
  const listBody = (withBatch: boolean, emptyMessage: string) =>
    loading && candidates.length === 0 ? (
      <ListSkeleton rows={4} />
    ) : candidates.length === 0 ? (
      <EmptyState illustration={<EmptyInbox />} message={emptyMessage} />
    ) : (
      <>
        {withBatch && (
          <div className="flex items-center justify-between mb-2 px-1">
            <div className="flex items-center gap-2">
              <Checkbox
                checked={selectedIds.size === candidates.length && candidates.length > 0}
                onCheckedChange={() => {
                  toggleSelectAll()
                  setBatchConfirmAction(null)
                }}
              />
              <span className="text-sm text-[var(--text-secondary)]">{t.inbox.selectAll}</span>
            </div>
            <div className="hidden sm:flex items-center gap-2 text-xs text-[var(--text-tertiary)] opacity-0 hover:opacity-100 transition-opacity duration-200">
              <kbd className="border border-[var(--border-default)] px-1.5 py-0.5 bg-surface-elevated/30 rounded font-mono text-2xs">
                j/k
              </kbd>
              <span>{t.inbox.navigateHint}</span>
              <kbd className="border border-[var(--border-default)] px-1.5 py-0.5 bg-surface-elevated/30 rounded font-mono text-2xs">
                ⏎
              </kbd>
              <kbd className="border border-[var(--border-default)] px-1.5 py-0.5 bg-surface-elevated/30 rounded font-mono text-2xs">
                ␣
              </kbd>
            </div>
          </div>
        )}
        <Card className="divide-y divide-[var(--border-default)] overflow-hidden">
          {candidates.map((c, idx) => (
            <CandidateItem
              key={c.id}
              candidate={c}
              idx={idx}
              selected={selectedIds.has(c.id)}
              focused={idx === focusedIndex}
              navigated={navigatedCandidateId === c.id}
              showCheckbox={withBatch}
              onToggle={toggleSelect}
              onOpen={openDetail}
              onRevert={withBatch ? undefined : setRevertTarget}
            />
          ))}
        </Card>
        <Pagination
          total={total}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </>
    )

  const headerContent = (
    <div className="flex items-center justify-between gap-4">
      <PageTitle icon={<Inbox size={18} />} title={t.inbox.title} />
      <div className="flex items-center gap-2">
        <CandidateQualityCard />
        <Button
          onClick={() => candidatesQuery.refetch()}
          disabled={loading}
          variant="secondary"
          className="flex items-center gap-1.5"
        >
          <Loader2 size={14} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
          <span className="hidden sm:inline">{t.common.refresh}</span>
        </Button>
      </div>
    </div>
  )

  return (
    <PageShell maxWidth="max-w-6xl" header={headerContent}>
      {/* Tab 切换控件——始终固定在顶部 */}
      <div className="mb-5">
        <SegmentedControl
          value={activeTab}
          onChange={setActiveTab}
          options={[
            // 待审/已生效的 total 跟随当前查询，仅在对应 tab 激活时展示，避免切换后计数失真
            {
              value: 'candidates',
              label: t.home.candidates,
              count: activeTab === 'candidates' ? pendingTotal : undefined,
            },
            {
              value: 'approved',
              label: t.inbox.tabApproved,
              count: activeTab === 'approved' ? pendingTotal : undefined,
            },
            { value: 'conflicts', label: t.nav.conflicts, count: conflicts.length },
          ]}
        />
      </div>

      <AnimatePresence mode="wait">
        {activeTab === 'candidates' && (
          <motion.div
            key="candidates"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: duration.slow, ease: [0.34, 1.56, 0.64, 1] }}
          >
            <AnimatePresence mode="wait">
              {selectedIds.size > 0 ? (
                batchConfirmAction ? (
                  <motion.div
                    key="batch-confirm"
                    initial={{ opacity: 0, y: -8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={spring.snappy}
                    className="mb-4 flex items-center justify-between gap-3 px-4 py-3 glass rounded-xl"
                  >
                    <span className="text-sm text-[var(--text-secondary)]">
                      {batchConfirmAction === 'approve'
                        ? translate(t.inbox.confirmBatchApprove, { n: selectedIds.size })
                        : translate(t.inbox.confirmBatchReject, { n: selectedIds.size })}
                    </span>
                    <div className="flex items-center gap-2">
                      <Button
                        onClick={() => setBatchConfirmAction(null)}
                        variant="secondary"
                        size="sm"
                      >
                        {t.common.cancel}
                      </Button>
                      <Button
                        onClick={() => {
                          handleBatchAction(batchConfirmAction)
                          setBatchConfirmAction(null)
                        }}
                        disabled={batchActionLoading !== null}
                        variant={batchConfirmAction === 'approve' ? 'success' : 'danger'}
                        size="sm"
                      >
                        {batchActionLoading ? <Loader2 size={14} className="animate-spin" /> : null}
                        {batchActionLoading ? t.inbox.processing : t.common.confirm}
                      </Button>
                    </div>
                  </motion.div>
                ) : (
                  <motion.div
                    key="batch-actions"
                    initial={{ opacity: 0, y: -8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={spring.snappy}
                    className="mb-4 flex items-center justify-between gap-3 px-4 py-3 glass rounded-xl"
                  >
                    <span className="text-sm text-[var(--text-secondary)]">
                      {translate(t.inbox.selectedCount, { n: selectedIds.size })}
                    </span>
                    <div className="flex items-center gap-2">
                      <Button
                        onClick={() => setBatchConfirmAction('reject')}
                        disabled={batchActionLoading !== null}
                        variant="danger"
                        size="sm"
                      >
                        {t.inbox.batchReject}
                      </Button>
                      <Button
                        onClick={() => setBatchConfirmAction('approve')}
                        disabled={batchActionLoading !== null}
                        variant="success"
                        size="sm"
                      >
                        {t.inbox.batchApprove}
                      </Button>
                    </div>
                  </motion.div>
                )
              ) : (
                filterSection
              )}
            </AnimatePresence>

            {error && (
              <ErrorAlert
                message={error}
                onRetry={() => candidatesQuery.refetch()}
                retryLabel={t.common.retry}
                className="mb-4"
              />
            )}

            {listBody(true, t.inbox.empty)}
          </motion.div>
        )}

        {/* 已生效 tab：查看 auto-approve / 人工批准的候选，支持撤销自动生效 */}
        {activeTab === 'approved' && (
          <motion.div
            key="approved"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: duration.slow, ease: [0.34, 1.56, 0.64, 1] }}
          >
            {filterSection}

            {error && (
              <ErrorAlert
                message={error}
                onRetry={() => candidatesQuery.refetch()}
                retryLabel={t.common.retry}
                className="mb-4"
              />
            )}

            {listBody(false, t.inbox.emptyApproved)}
          </motion.div>
        )}

        {activeTab === 'conflicts' && (
          <motion.div
            key="conflicts"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: duration.slow, ease: [0.34, 1.56, 0.64, 1] }}
          >
            <Suspense fallback={<ListSkeleton rows={4} />}>
              <ConflictsTab />
            </Suspense>
          </motion.div>
        )}
      </AnimatePresence>

      {detailCandidate && (
        <Suspense fallback={null}>
          <CandidateDetailModal
            candidate={detailCandidate}
            actionLoading={actionLoading}
            onClose={() => setDetailCandidate(null)}
            onReview={handleReview}
            onEdit={setEditCandidate}
            onMerge={setMergeCandidate}
            onUpdate={handleUpdate}
            onNavigateToMemory={async (id) => {
              try {
                const mem = await api.getMemoryDetail(id)
                setDetailMemory(mem)
              } catch {
                toast(t.memories.detailLoadFailed, 'error')
              }
            }}
          />
        </Suspense>
      )}

      {editCandidate && (
        <Suspense fallback={null}>
          <CandidateEditModal
            candidate={editCandidate}
            actionLoading={actionLoading}
            onClose={() => setEditCandidate(null)}
            onSubmit={handleEditSubmit}
          />
        </Suspense>
      )}

      {mergeCandidate && (
        <Suspense fallback={null}>
          <CandidateMergeModal
            candidate={mergeCandidate}
            onClose={() => setMergeCandidate(null)}
            onMerged={async () => {
              await candidatesQuery.refetch()
            }}
          />
        </Suspense>
      )}

      {/* 撤销自动生效确认对话框 */}
      <Dialog
        open={revertTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRevertTarget(null)
        }}
        title={t.inbox.revertTitle}
        description={revertTarget?.title}
        size="sm"
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setRevertTarget(null)}>
              {t.common.cancel}
            </Button>
            <Button
              variant="warning"
              size="sm"
              onClick={handleRevertConfirm}
              disabled={revertPending}
            >
              {revertPending ? (
                <Loader2 size={14} className="animate-spin" aria-hidden="true" />
              ) : (
                <Undo2 size={14} aria-hidden="true" />
              )}
              {revertPending ? t.inbox.revertProcessing : t.inbox.revert}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {t.inbox.revertConfirmDesc}
        </p>
      </Dialog>

      <Suspense fallback={null}>
        <MemoryDetailModal
          memory={detailMemory}
          onClose={() => setDetailMemory(null)}
          onMemoryUpdated={() => {}}
        />
      </Suspense>
    </PageShell>
  )
}
