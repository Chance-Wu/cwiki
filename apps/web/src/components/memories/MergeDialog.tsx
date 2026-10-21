import { lazy, Suspense, useEffect } from 'react'
import { useTranslation } from '../../i18n/I18nProvider'
import { Loader2, ArrowRight, Info } from 'lucide-react'
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
      description={t.memories.mergeDialogDesc}
      size="xl"
      footer={
        <div className="flex justify-between items-center w-full">
          <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)]">
            <Info size={14} />
            <span>{t.memories.mergeArchivedHint}</span>
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
      {/* Memory Cards */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-3 mb-4">
        {/* Target Memory (Keeper) */}
        <div className="p-4 bg-surface-inset rounded-lg border-2 border-[var(--border-default)] shadow-warm-xs">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full bg-primary" />
            <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">
              {t.memories.mergeInto}
            </span>
          </div>
          <div className="text-base font-semibold text-[var(--text-primary)] mb-1 line-clamp-2">
            {mergeTarget?.target_title}
          </div>
          {mergeTargetFilePath && (
            <div className="text-xs text-[var(--text-tertiary)] font-mono truncate">
              {mergeTargetFilePath}
            </div>
          )}
        </div>

        {/* Arrow Indicator */}
        <div className="hidden md:flex items-center justify-center">
          <div className="w-10 h-10 rounded-full bg-warning/15 border border-warning/30 flex items-center justify-center">
            <ArrowRight size={18} className="text-warning-fg" />
          </div>
        </div>

        {/* Source Memory (To be archived) */}
        <div className="p-4 bg-warning-bg rounded-lg border-2 border-warning-border shadow-warm-xs">
          <div className="flex items-center justify-between gap-2 mb-2">
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
              {similarityPercent}% {t.memories.mergeSimilarity}
            </div>
          </div>
          <div className="text-base font-semibold text-[var(--text-primary)] mb-1 line-clamp-2">
            {mergeTarget?.source_title}
          </div>
          {mergeSourceFilePath && (
            <div className="text-xs text-[var(--text-tertiary)] font-mono truncate">
              {mergeSourceFilePath}
            </div>
          )}
        </div>
      </div>

      {/* Merge Reason */}
      <div className="mb-4 p-3 bg-primary/5 border border-primary/20 rounded-lg">
        <div className="flex items-start gap-2">
          <Info size={16} className="text-primary shrink-0 mt-0.5" />
          <div className="flex-1 text-sm">
            <div className="font-semibold text-[var(--text-primary)] mb-1">
              {t.memories.mergeWhyTitle}
            </div>
            <div className="text-[var(--text-secondary)] space-y-1">
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
        </div>
      </div>

      {/* Diff View */}
      {mergeLoading ? (
        <div className="mb-4 p-8 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs flex items-center justify-center gap-2 text-sm text-[var(--text-secondary)]">
          <Loader2 size={16} className="animate-spin" />
          {t.common.loading}
        </div>
      ) : (
        <div className="mb-4">
          <label className="block text-sm font-semibold text-[var(--text-primary)] mb-2">
            {t.memories.mergeDiff}
          </label>
          <Suspense
            fallback={
              <div className="p-8 flex items-center justify-center gap-2 text-sm text-[var(--text-tertiary)]">
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
    </Dialog>
  )
}
