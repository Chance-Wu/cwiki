import { lazy, Suspense, useEffect, useState } from 'react'
import { useTranslation } from '../../i18n/I18nProvider'
import { Loader2, ArrowRight, Info, ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import type { MergeSuggestion } from '../../lib/api'
import { getSimilarityColor } from '../../lib/utils/similarity'

const MergeDiffView = lazy(() => import('../MergeDiffView'))

interface MergeDialogProps {
  mergeTarget: MergeSuggestion | null
  mergedContent: string
  mergeSourceContent: string
  mergeTargetContent: string
  mergeSourceFilePath: string
  mergeTargetFilePath: string
  mergeLoading: boolean
  mergeMutationPending: boolean
  onClose: () => void
  onMergedChange: (value: string) => void
  onConfirm: () => void
}

export default function MergeDialog({
  mergeTarget,
  mergedContent,
  mergeSourceContent,
  mergeTargetContent,
  mergeSourceFilePath,
  mergeTargetFilePath,
  mergeLoading,
  mergeMutationPending,
  onClose,
  onMergedChange,
  onConfirm,
}: MergeDialogProps) {
  const { t } = useTranslation()
  const [reasonExpanded, setReasonExpanded] = useState(false)

  // Keyboard shortcuts
  useEffect(() => {
    if (!mergeTarget) return

    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + Enter: Confirm merge
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault()
        if (!mergeMutationPending && mergedContent.trim() && !mergeLoading) {
          onConfirm()
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [mergeTarget, mergeMutationPending, mergedContent, mergeLoading, onConfirm])

  const similarityPercent = mergeTarget ? Math.round(mergeTarget.similarity * 100) : 0

  return (
    <Dialog
      open={!!mergeTarget}
      onOpenChange={(o) => !o && onClose()}
      title={t.memories.mergeConfirm}
      size="xl"
      fixedHeight
      footer={
        <div className="flex justify-between items-center w-full">
          <div className="flex items-center gap-3 text-xs text-[var(--text-tertiary)]">
            <span className="flex items-center gap-1.5">
              <Info size={12} />
              <span>{t.memories.mergeArchivedHint}</span>
            </span>
            <span className="text-[var(--border-default)]">|</span>
            <kbd className="px-1 py-0.5 bg-surface-inset rounded text-[10px] font-mono border border-[var(--border-default)]">Ctrl</kbd>
            <span>+</span>
            <kbd className="px-1 py-0.5 bg-surface-inset rounded text-[10px] font-mono border border-[var(--border-default)]">Enter</kbd>
            <span>{t.memories.mergeAction}</span>
          </div>
          <div className="flex gap-2">
            <Button onClick={onClose} variant="secondary" size="sm">
              {t.memories.dismissMerge}
            </Button>
            <Button
              onClick={onConfirm}
              disabled={mergeMutationPending || !mergedContent.trim() || mergeLoading}
              variant="primary"
              size="sm"
              className="shadow-warm-sm"
            >
              {mergeMutationPending ? (
                <>
                  <Loader2 size={14} className="animate-spin mr-1.5" />
                  {t.memories.merging}
                </>
              ) : (
                <>
                  <ArrowRight size={14} className="mr-1.5" />
                  {t.memories.mergeAction}
                </>
              )}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col min-h-0 flex-1">
        {/* Memory Cards - compact header */}
        <div className="shrink-0 grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-3 pb-3">
          {/* Target Memory (Keeper) */}
          <div className="px-3 py-2 bg-surface-inset rounded-lg border border-[var(--border-default)]">
            <div className="flex items-center gap-2 mb-1">
              <div className="w-2 h-2 rounded-full bg-primary" />
              <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">
                {t.memories.mergeInto}
              </span>
            </div>
            <div className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {mergeTarget?.target_title}
            </div>
          </div>

          {/* Arrow Indicator */}
          <div className="hidden md:flex items-center justify-center">
            <div className="w-8 h-8 rounded-full bg-warning/15 border border-warning/30 flex items-center justify-center">
              <ArrowRight size={14} className="text-warning-fg" />
            </div>
          </div>

          {/* Source Memory (To be archived) */}
          <div className="px-3 py-2 bg-warning-bg rounded-lg border border-warning-border">
            <div className="flex items-center justify-between gap-2 mb-1">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-warning-fg" />
                <span className="text-xs font-semibold text-warning-fg uppercase tracking-wide">
                  {t.memories.mergeSource}
                </span>
              </div>
              <div
                className={`px-2 py-0.5 rounded-full text-xs font-semibold tabular-nums border ${getSimilarityColor(
                  similarityPercent,
                  true,
                  true,
                )}`}
              >
                {similarityPercent}%
              </div>
            </div>
            <div className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {mergeTarget?.source_title}
            </div>
          </div>
        </div>

        {/* Merge Reason - inline compact */}
        <div className="shrink-0 mb-3">
          <button
            onClick={() => setReasonExpanded(!reasonExpanded)}
            className="w-full px-3 py-1.5 bg-primary/5 border border-primary/15 rounded-lg flex items-center gap-2 hover:bg-primary/10 transition-colors text-left"
          >
            <Info size={12} className="text-primary shrink-0" />
            <span className="flex-1 text-xs font-medium text-[var(--text-secondary)]">
              {t.memories.mergeWhyTitle}
              {similarityPercent > 0 && (
                <span className="ml-1.5 text-[var(--text-tertiary)]">({similarityPercent}%)</span>
              )}
            </span>
            {reasonExpanded ? (
              <ChevronUp size={12} className="text-[var(--text-tertiary)]" />
            ) : (
              <ChevronDown size={12} className="text-[var(--text-tertiary)]" />
            )}
          </button>
          {reasonExpanded && (
            <div className="mt-1 px-3 py-1.5 bg-primary/5 border border-primary/10 rounded-lg">
              <div className="text-xs text-[var(--text-secondary)] space-y-0.5">
                {similarityPercent >= 90 && (
                  <div>• {t.memories.mergeReasonHighOverlap.replace('{n}', String(similarityPercent))}</div>
                )}
                {similarityPercent >= 75 && similarityPercent < 90 && (
                  <div>• {t.memories.mergeReasonMediumOverlap.replace('{n}', String(similarityPercent))}</div>
                )}
                {mergeTarget?.relation_type && (
                  <div>• {t.memories.mergeReasonRelation.replace('{type}', mergeTarget.relation_type.replace(/_/g, ' '))}</div>
                )}
                {mergeTarget?.strategy && (
                  <div>• {t.memories.mergeReasonStrategy.replace('{strategy}', mergeTarget.strategy)}</div>
                )}
                <div>• {t.memories.mergeReasonConsolidate}</div>
              </div>
            </div>
          )}
        </div>

        {/* Diff View - fills remaining space */}
        {mergeLoading ? (
          <div className="flex-1 min-h-0 p-8 bg-surface-inset rounded-lg border border-[var(--border-default)] flex items-center justify-center gap-2 text-sm text-[var(--text-secondary)]">
            <Loader2 size={16} className="animate-spin" />
            {t.common.loading}
          </div>
        ) : (
          <div className="flex-1 min-h-0 flex flex-col">
            <Suspense
              fallback={
                <div className="flex-1 p-8 flex items-center justify-center gap-2 text-sm text-[var(--text-tertiary)]">
                  <Loader2 size={16} className="animate-spin" />
                  {t.common.loading}
                </div>
              }
            >
              <MergeDiffView
                targetContent={mergeTargetContent}
                sourceContent={mergeSourceContent}
                mergedContent={mergedContent}
                onMergedChange={onMergedChange}
                targetTitle={mergeTarget?.target_title}
                sourceTitle={mergeTarget?.source_title}
                targetFilePath={mergeTargetFilePath || undefined}
                sourceFilePath={mergeSourceFilePath || undefined}
              />
            </Suspense>
          </div>
        )}
      </div>
    </Dialog>
  )
}
