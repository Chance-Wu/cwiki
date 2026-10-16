import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from '../../i18n/I18nProvider'
import { type Candidate, type FileMemory, api as apiClient } from '../../lib/api'
import { typeLabel } from '../../lib/labels'
import { Dialog } from '../ui/Dialog'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import MergeDiffView from '../MergeDiffView'
import { useModal } from '../../hooks/useModal'
import { useToast } from '../Toast'
import { GitMerge, ArrowUpCircle, AlertTriangle, Copy, Search, X, Loader2 } from 'lucide-react'

interface CandidateMergeModalProps {
  candidate: Candidate | null
  onClose: () => void
  onMerged: () => Promise<void>
}

const RELATION_CONFIG: Record<string, { icon: typeof GitMerge; color: string; bgColor: string }> = {
  DUPLICATE: {
    icon: Copy,
    color: 'text-danger-fg',
    bgColor: 'bg-danger-bg border border-danger-border',
  },
  MERGE: { icon: GitMerge, color: 'text-info-fg', bgColor: 'bg-info-bg border border-info-border' },
  UPDATE: {
    icon: ArrowUpCircle,
    color: 'text-warning-fg',
    bgColor: 'bg-warning-bg border border-warning-border',
  },
  CONFLICT: {
    icon: AlertTriangle,
    color: 'text-danger-fg',
    bgColor: 'bg-danger-bg border border-danger-border',
  },
}

interface TargetOption {
  id: string
  title: string
  type: string
  source: 'memory' | 'candidate'
  content_preview: string
}

export default function CandidateMergeModal({
  candidate,
  onClose,
  onMerged,
}: CandidateMergeModalProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  useModal(!!candidate, onClose)
  const [selectedTargetId, setSelectedTargetId] = useState('')
  const [selectedTargetSource, setSelectedTargetSource] = useState<'memory' | 'candidate' | null>(
    null,
  )
  const [mergedContent, setMergedContent] = useState('')
  const [confirmMerge, setConfirmMerge] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [targetFullContent, setTargetFullContent] = useState('')
  const [targetFilePath, setTargetFilePath] = useState('')
  const [targetLoading, setTargetLoading] = useState(false)
  const [targetTitle, setTargetTitle] = useState('')

  // 手动选择合并目标的交互状态
  const [showTargetPicker, setShowTargetPicker] = useState(false)
  const [targetSearch, setTargetSearch] = useState('')
  const [targetOptions, setTargetOptions] = useState<TargetOption[]>([])
  const [targetOptionsLoading, setTargetOptionsLoading] = useState(false)
  const pickerRef = useRef<HTMLDivElement>(null)

  // 点击选择器外部时关闭
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setShowTargetPicker(false)
      }
    }
    if (showTargetPicker) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showTargetPicker])

  // 拉取手动选择的目标候选：已入库记忆 + 其他待审候选（排除自身）
  const loadTargetOptions = useCallback(
    async (search: string) => {
      setTargetOptionsLoading(true)
      try {
        const [memoriesRes, candidatesRes] = await Promise.all([
          apiClient.getMemories({ limit: 50, status: 'active' }),
          apiClient.getCandidates({ limit: 50, status: 'pending_review' }),
        ])
        const memoryOptions: TargetOption[] = memoriesRes.items.map((m: FileMemory) => ({
          id: m.id,
          title: m.title,
          type: m.type,
          source: 'memory' as const,
          content_preview: m.content?.slice(0, 100) ?? '',
        }))
        const candidateOptions: TargetOption[] = candidatesRes.items
          .filter((c: Candidate) => c.id !== candidate?.id) // 排除当前候选自身
          .map((c: Candidate) => ({
            id: c.id,
            title: c.title,
            type: c.type,
            source: 'candidate' as const,
            content_preview: c.content?.slice(0, 100) ?? '',
          }))
        const all = [...memoryOptions, ...candidateOptions]
        if (search.trim()) {
          const q = search.trim().toLowerCase()
          setTargetOptions(all.filter((o) => o.title.toLowerCase().includes(q)))
        } else {
          setTargetOptions(all)
        }
      } catch {
        setTargetOptions([])
        toast(t.inbox.loadFailed, 'error')
      } finally {
        setTargetOptionsLoading(false)
      }
    },
    [candidate?.id, t.inbox.loadFailed, toast],
  )

  // 选中目标变化时加载其完整内容，供三栏对比展示
  useEffect(() => {
    if (!selectedTargetId) {
      setTargetFullContent('')
      setTargetFilePath('')
      setTargetTitle('')
      return
    }
    setTargetLoading(true)

    const applyMemory = (mem: { content: string; file_path?: string; title: string }) => {
      setTargetFullContent(mem.content)
      setTargetFilePath(mem.file_path ?? '')
      setTargetTitle(mem.title)
      if (mem.content && candidate) {
        setMergedContent(`${mem.content}\n\n---\n\n${candidate.content}`)
      }
    }

    if (selectedTargetSource === 'candidate') {
      apiClient
        .getCandidate(selectedTargetId)
        .then((c) => applyMemory({ content: c.content, title: c.title }))
        .catch(() => {
          setTargetFullContent('')
          setTargetTitle('')
          toast(t.inbox.loadFailed, 'error')
        })
        .finally(() => setTargetLoading(false))
    } else {
      apiClient
        .getMemoryDetail(selectedTargetId)
        .then((mem) => applyMemory(mem))
        .catch(() => {
          setTargetFullContent('')
          setTargetTitle('')
          toast(t.inbox.loadFailed, 'error')
        })
        .finally(() => setTargetLoading(false))
    }
  }, [selectedTargetId, selectedTargetSource, candidate, toast, t.inbox.loadFailed])

  useEffect(() => {
    if (!candidate) {
      setConfirmMerge(false)
      setTargetFullContent('')
      setTargetFilePath('')
      setTargetTitle('')
      setSelectedTargetId('')
      setSelectedTargetSource(null)
      setShowTargetPicker(false)
      setTargetSearch('')
      return
    }
    setConfirmMerge(false)
    setMergedContent(candidate.content)

    if (
      candidate.similar_memory_id &&
      (candidate.similar_memory_source === 'memory' ||
        candidate.similar_memory_source === 'candidate')
    ) {
      setSelectedTargetId(candidate.similar_memory_id)
      setSelectedTargetSource(candidate.similar_memory_source)
      setTargetTitle(candidate.similar_memory_title ?? '')
    } else {
      setSelectedTargetId('')
      setSelectedTargetSource(null)
      setTargetTitle('')
    }
  }, [candidate])

  const handleSubmit = async () => {
    if (!candidate || !selectedTargetId) return
    setSubmitting(true)
    try {
      await apiClient.reviewCandidate(candidate.id, 'merge', {
        merged_content: mergedContent,
        merge_target_memory_id: selectedTargetId,
      })
      await onMerged()
      onClose()
    } catch {
      toast(t.inbox.mergeFailed, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSelectTarget = (option: TargetOption) => {
    setSelectedTargetId(option.id)
    setSelectedTargetSource(option.source)
    setTargetTitle(option.title)
    setShowTargetPicker(false)
    setTargetSearch('')
  }

  const relation = candidate?.similar_memory_relation
  const relationConfig = relation ? RELATION_CONFIG[relation] : null
  const RelationIcon = relationConfig?.icon
  const hasRecommendedTarget =
    candidate?.similar_memory_id &&
    (candidate?.similar_memory_source === 'memory' ||
      candidate?.similar_memory_source === 'candidate')

  return (
    <Dialog
      open={!!candidate}
      size="xl"
      title={t.inbox.mergeTitle}
      fixedHeight
      footer={
        <div
          key={confirmMerge ? 'confirm' : 'actions'}
          className="flex justify-end gap-2 animate-[fade-in_0.15s_ease-out]"
        >
          {confirmMerge ? (
            <>
              <span className="text-sm text-[var(--text-secondary)] flex items-center mr-auto">
                {t.inbox.confirmMergeLabel}
              </span>
              <Button variant="secondary" onClick={() => setConfirmMerge(false)}>
                {t.common.cancel}
              </Button>
              <Button
                variant="success"
                onClick={handleSubmit}
                disabled={submitting || !selectedTargetId || !mergedContent.trim()}
              >
                {submitting ? t.inbox.processing : t.common.confirm}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="secondary"
                onClick={() => {
                  setConfirmMerge(false)
                  onClose()
                }}
              >
                {t.inbox.cancel}
              </Button>
              <Button
                onClick={() => setConfirmMerge(true)}
                disabled={!selectedTargetId || !mergedContent.trim()}
              >
                {t.inbox.save}
              </Button>
            </>
          )}
        </div>
      }
      onOpenChange={(o) => {
        if (!o) {
          setConfirmMerge(false)
          onClose()
        }
      }}
    >
      {candidate && (
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
          <div className="space-y-4">
            {/* 合并目标选择 */}
            <div>
              <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
                {t.inbox.mergeTarget}
              </label>

              {hasRecommendedTarget ? (
                // 后端推荐的合并目标展示
                <div
                  className={`border rounded-lg p-3 ${relationConfig?.bgColor ?? 'bg-surface-inset rounded-lg border-[var(--border-default)]'}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <h4 className="font-medium text-[var(--text-primary)] break-words">
                        {candidate.similar_memory_title}
                      </h4>
                      <div className="flex items-center gap-2 mt-1.5">
                        {candidate.similar_memory_type && (
                          <Badge className="bg-surface-inset text-[var(--text-secondary)] border border-[var(--border-default)] shadow-warm-xs">
                            {typeLabel(t.common, candidate.similar_memory_type)}
                          </Badge>
                        )}
                        {candidate.similar_memory_source === 'candidate' && (
                          <Badge variant="warning">{t.inbox.candidateTarget}</Badge>
                        )}
                        {relation && RelationIcon && (
                          <Badge
                            className={`gap-1 ${relationConfig?.color} bg-surface-inset border border-[var(--border-default)] shadow-warm-xs`}
                          >
                            <RelationIcon size={12} aria-hidden="true" />
                            {t.inbox[
                              `relation_${relation.toLowerCase()}` as keyof typeof t.inbox
                            ] || relation}
                          </Badge>
                        )}
                        {candidate.duplicate_probability != null && (
                          <span className="text-xs text-[var(--text-secondary)]">
                            {t.inbox.similarityLabel}{' '}
                            <span className="tabular-nums">
                              {Math.round(candidate.duplicate_probability * 100)}
                            </span>
                            %
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  {candidate.similar_memory_content_preview && (
                    <p className="text-sm text-[var(--text-secondary)] mt-2 line-clamp-3">
                      {candidate.similar_memory_content_preview}
                    </p>
                  )}
                </div>
              ) : (
                // 手动选择目标
                <div className="relative" ref={pickerRef}>
                  <button
                    aria-label={t.inbox.selectMergeTarget}
                    aria-expanded={showTargetPicker}
                    aria-haspopup="listbox"
                    onClick={() => {
                      setShowTargetPicker(!showTargetPicker)
                      if (!showTargetPicker && targetOptions.length === 0) {
                        loadTargetOptions('')
                      }
                    }}
                    className="w-full flex items-center justify-between px-3 py-2 text-sm bg-surface-inset border border-[var(--border-default)] rounded-lg text-[var(--text-primary)] hover:border-[var(--border-strong)] transition-all duration-150 select-none"
                  >
                    <span
                      className={
                        selectedTargetId
                          ? 'text-[var(--text-primary)]'
                          : 'text-[var(--text-tertiary)]'
                      }
                    >
                      {selectedTargetId
                        ? targetTitle || t.inbox.selectTarget
                        : t.inbox.selectTarget}
                    </span>
                    <Search size={14} className="text-[var(--text-tertiary)]" aria-hidden="true" />
                  </button>

                  {showTargetPicker && (
                    <div className="absolute z-dropdown mt-1 w-full glass-heavy rounded-lg max-h-96 !overflow-y-auto scrollbar-thin flex flex-col animate-fade-in">
                      <div className="p-2 border-b border-[var(--glass-border)]">
                        <div className="relative">
                          <Search
                            size={14}
                            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]"
                            aria-hidden="true"
                          />
                          <Input
                            type="text"
                            value={targetSearch}
                            onChange={(e) => {
                              setTargetSearch(e.target.value)
                              loadTargetOptions(e.target.value)
                            }}
                            placeholder={t.inbox.searchTarget}
                            className="pl-8 pr-8 py-1.5"
                            autoFocus
                          />
                          {targetSearch && (
                            <button
                              onClick={() => {
                                setTargetSearch('')
                                loadTargetOptions('')
                              }}
                              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-all duration-150 active:scale-95 select-none"
                              aria-label={t.common.close}
                            >
                              <X size={14} aria-hidden="true" />
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="overflow-y-auto flex-1 scrollbar-thin">
                        {targetOptionsLoading ? (
                          <div className="p-4 text-center text-sm text-[var(--text-secondary)] flex items-center justify-center gap-2">
                            <Loader2 size={14} className="animate-spin" />
                            {t.common.loading}
                          </div>
                        ) : targetOptions.length === 0 ? (
                          <div className="p-4 text-center text-sm text-[var(--text-secondary)]">
                            {t.inbox.noTargetsFound}
                          </div>
                        ) : (
                          targetOptions.map((option) => (
                            <button
                              key={option.id}
                              aria-label={option.title || option.id.slice(0, 8)}
                              onClick={() => handleSelectTarget(option)}
                              className={`w-full text-left px-3 py-2 hover:bg-surface-inset transition-all duration-150 select-none border-b border-[var(--border-default)] last:border-0 ${
                                option.id === selectedTargetId ? 'bg-surface-inset' : ''
                              }`}
                            >
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-[var(--text-primary)] truncate flex-1">
                                  {option.title}
                                </span>
                                <Badge className="bg-surface-inset text-[var(--text-secondary)] border border-[var(--border-default)] shadow-warm-xs shrink-0">
                                  {typeLabel(t.common, option.type)}
                                </Badge>
                                {option.source === 'candidate' && (
                                  <Badge variant="warning" className="shrink-0">
                                    {t.inbox.candidateTarget}
                                  </Badge>
                                )}
                              </div>
                              {option.content_preview && (
                                <p className="text-xs text-[var(--text-secondary)] mt-1 truncate">
                                  {option.content_preview}
                                </p>
                              )}
                            </button>
                          ))
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 三栏合并对比视图 */}
            {targetFullContent && !targetLoading && (
              <div>
                <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
                  {t.inbox.mergeDiff}
                </label>
                <MergeDiffView
                  targetContent={targetFullContent}
                  sourceContent={candidate.content}
                  mergedContent={mergedContent}
                  onMergedChange={setMergedContent}
                  targetTitle={targetTitle || candidate.similar_memory_title || undefined}
                  sourceTitle={candidate.title}
                  targetFilePath={targetFilePath || undefined}
                />
              </div>
            )}
            {targetLoading && (
              <div className="p-3 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs text-center text-sm text-[var(--text-secondary)] flex items-center justify-center gap-2">
                <Loader2 size={14} className="animate-spin" />
                {t.common.loading}
              </div>
            )}
          </div>
        </div>
      )}
    </Dialog>
  )
}
