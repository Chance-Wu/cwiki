import { lazy, Suspense } from 'react'
import { useTranslation } from '../../i18n/I18nProvider'
import { Loader2 } from 'lucide-react'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import type { MergeSuggestion } from '../../lib/api'

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

  return (
    <Dialog
      open={!!mergeTarget}
      onOpenChange={(o) => !o && onClose()}
      title={t.memories.mergeConfirm}
      description={t.memories.mergeConfirmDesc}
      size="xl"
      footer={
        <div className="flex justify-end gap-2">
          <Button onClick={onClose} variant="secondary" size="sm">
            {t.memories.dismissMerge}
          </Button>
          <Button
            onClick={onConfirm}
            disabled={mergeMutationPending || !mergedContent.trim() || mergeLoading}
          >
            {mergeMutationPending ? t.memories.merging : t.memories.mergeAction}
          </Button>
        </div>
      }
    >
      <div className="space-y-2 mb-4">
        <div className="p-3 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs">
          <div className="text-sm text-[var(--text-secondary)] mb-1">{t.memories.mergeInto}</div>
          <div className="text-base font-medium text-[var(--text-primary)]">
            {mergeTarget?.target_title}
          </div>
        </div>
        <div className="p-3 bg-warning-bg rounded-lg border border-warning-border">
          <div className="text-sm text-warning-fg mb-1">{t.memories.mergeSimilarity}</div>
          <div className="text-base font-medium text-[var(--text-primary)]">
            {mergeTarget?.source_title}
          </div>
          <div className="text-sm text-warning-fg mt-1 tabular-nums">
            {mergeTarget && Math.round(mergeTarget.similarity * 100)}%
          </div>
        </div>
      </div>

      {/* 三栏合并对比视图 */}
      {mergeLoading ? (
        <div className="mb-4 p-6 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs flex items-center justify-center gap-2 text-sm text-[var(--text-secondary)]">
          <Loader2 size={14} className="animate-spin" />
          {t.common.loading}
        </div>
      ) : (
        <div className="mb-4">
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            {t.memories.mergeDiff}
          </label>
          <Suspense
            fallback={
              <div className="p-8 flex items-center justify-center gap-2 text-sm text-[var(--text-tertiary)]">
                <Loader2 size={14} className="animate-spin" />
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
