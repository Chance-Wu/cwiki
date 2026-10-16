import { motion } from 'framer-motion'
import { spring } from '../../lib/motion'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { Trash2, Loader2 } from 'lucide-react'
import { Button } from '../ui/Button'

interface BatchActionBarProps {
  selectedCount: number
  batchDeleteConfirm: boolean
  batchDeleteLoading: boolean
  onCancel: () => void
  onDeleteClick: () => void
  onBatchDelete: () => void
}

export default function BatchActionBar({
  selectedCount,
  batchDeleteConfirm,
  batchDeleteLoading,
  onCancel,
  onDeleteClick,
  onBatchDelete,
}: BatchActionBarProps) {
  const { t } = useTranslation()

  return (
    <motion.div
      className="mb-4 flex items-center justify-between px-4 py-2.5 bg-surface-elevated/60 border border-[var(--glass-border)] rounded-lg shadow-warm-sm"
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', ...spring.snappy }}
    >
      <span className="text-xs text-[var(--text-primary)] font-semibold">
        {translate(t.memories.selectedCount, { n: selectedCount })}
      </span>
      <div className="flex items-center gap-2">
        {batchDeleteConfirm ? (
          <>
            <span className="text-sm text-danger-fg">
              {translate(t.memories.confirmBatchDelete, { n: selectedCount })}
            </span>
            <Button variant="secondary" onClick={onCancel}>
              {t.common.cancel}
            </Button>
            <Button variant="danger" onClick={onBatchDelete}>
              {batchDeleteLoading ? <Loader2 size={14} className="animate-spin" /> : null}
              {t.common.confirm}
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" onClick={onCancel}>
              {t.common.cancel}
            </Button>
            <Button variant="ghost" onClick={onDeleteClick}>
              <Trash2 size={14} />
              {t.memories.batchDelete}
            </Button>
          </>
        )}
      </div>
    </motion.div>
  )
}
