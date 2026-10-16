import { useTranslation } from '../../i18n/I18nProvider'
import { Dialog } from '../ui/Dialog'
import { Button } from '../ui/Button'
import MarkdownContent from '../MarkdownContent'
import type { OptimizePreview } from './MemoryDetailModal'

interface Props {
  preview: OptimizePreview | null
  applying: boolean
  onClose: () => void
  onApply: () => void
}

export default function MemoryOptimizePreviewModal({ preview, applying, onClose, onApply }: Props) {
  const { t } = useTranslation()

  if (!preview) return null

  return (
    <Dialog
      open={!!preview}
      onOpenChange={(o) => {
        if (!o) onClose()
      }}
      title={t.memories.optimize}
      size="xl"
      fixedHeight
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t.memories.discardOptimization}
          </Button>
          <Button onClick={onApply} disabled={applying}>
            {applying ? t.memories.optimizing : t.memories.applyOptimization}
          </Button>
        </div>
      }
    >
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
        {preview.changes && (
          <div className="mb-4 p-3 bg-surface-inset border border-[var(--border-default)] rounded-lg text-sm text-[var(--text-primary)]">
            <span className="font-medium">{t.memories.changes}:</span> {preview.changes}
          </div>
        )}
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
              {t.memories.titleLabel}
            </h4>
            <div className="text-sm text-[var(--text-tertiary)] line-through mb-1">
              {preview.originalTitle}
            </div>
            <div className="text-sm text-[var(--text-primary)] font-medium">
              {preview.optimizedTitle}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
          <div>
            <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
              {t.memories.originalContent}
            </h4>
            <div className="text-sm text-[var(--text-secondary)] bg-surface-inset rounded-lg p-3 border border-[var(--border-default)] shadow-warm-xs">
              <MarkdownContent content={preview.originalContent} />
            </div>
          </div>
          <div>
            <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
              {t.memories.optimizedContent}
            </h4>
            <div className="text-sm text-[var(--text-primary)] bg-success-bg rounded-lg p-3 border border-success-border">
              <MarkdownContent content={preview.optimizedContent} />
            </div>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
