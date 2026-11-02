import { useState } from 'react'
import { motion } from 'framer-motion'
import { spring } from '../../lib/motion'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { Trash2, Loader2, Pencil, Download } from 'lucide-react'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'

export interface BatchUpdatePatch {
  type?: string
  confidence?: number
  importance?: number
  tags?: string[]
}

interface BatchActionBarProps {
  selectedCount: number
  batchDeleteConfirm: boolean
  batchDeleteLoading: boolean
  batchUpdateLoading: boolean
  onCancel: () => void
  onDeleteClick: () => void
  onBatchDelete: () => void
  onBatchUpdate: (patch: BatchUpdatePatch) => void
  onExportSelected: () => void
}

const FIELD_CLASS =
  'rounded-lg border border-[var(--border-default)] bg-surface-card px-2 py-1.5 text-sm text-[var(--text-primary)] outline-none focus-visible:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-200/30'

export default function BatchActionBar({
  selectedCount,
  batchDeleteConfirm,
  batchDeleteLoading,
  batchUpdateLoading,
  onCancel,
  onDeleteClick,
  onBatchDelete,
  onBatchUpdate,
  onExportSelected,
}: BatchActionBarProps) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [patchType, setPatchType] = useState('')
  const [patchConfidence, setPatchConfidence] = useState('')
  const [patchImportance, setPatchImportance] = useState('')
  const [patchTags, setPatchTags] = useState('')

  const typeOptions = [
    { value: '', label: t.memories.keepUnchanged },
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
  ]

  const handleApply = () => {
    const patch: BatchUpdatePatch = {}
    if (patchType) patch.type = patchType
    if (patchConfidence !== '') patch.confidence = Number(patchConfidence)
    if (patchImportance !== '') patch.importance = Number(patchImportance)
    const tags = patchTags
      .split(/[,，\s]+/)
      .map((tag) => tag.trim())
      .filter(Boolean)
    if (tags.length > 0) patch.tags = tags
    if (Object.keys(patch).length === 0) return
    onBatchUpdate(patch)
  }

  return (
    <motion.div
      className="mb-4 flex flex-col gap-2 rounded-lg border border-[var(--glass-border)] bg-surface-elevated/60 px-4 py-2.5 shadow-warm-sm"
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', ...spring.snappy }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-[var(--text-primary)]">
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
          ) : editing ? (
            <>
              <Button variant="secondary" onClick={() => setEditing(false)}>
                {t.common.cancel}
              </Button>
              <Button onClick={handleApply} disabled={batchUpdateLoading}>
                {batchUpdateLoading ? <Loader2 size={14} className="animate-spin" /> : null}
                {t.common.confirm}
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" onClick={onCancel}>
                {t.common.cancel}
              </Button>
              <Button variant="ghost" onClick={onExportSelected}>
                <Download size={14} />
                {t.memories.exportSelected}
              </Button>
              <Button variant="ghost" onClick={() => setEditing(true)}>
                <Pencil size={14} />
                {t.memories.batchEdit}
              </Button>
              <Button variant="ghost" onClick={onDeleteClick}>
                <Trash2 size={14} />
                {t.memories.batchDelete}
              </Button>
            </>
          )}
        </div>
      </div>

      {editing && (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            options={typeOptions}
            value={patchType}
            onChange={setPatchType}
            placeholder={t.memories.keepUnchanged}
          />
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={patchConfidence}
            onChange={(e) => setPatchConfidence(e.target.value)}
            placeholder={t.memories.confidence}
            aria-label={t.memories.confidence}
            className={`w-24 ${FIELD_CLASS}`}
          />
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={patchImportance}
            onChange={(e) => setPatchImportance(e.target.value)}
            placeholder={t.memories.importance}
            aria-label={t.memories.importance}
            className={`w-24 ${FIELD_CLASS}`}
          />
          <input
            type="text"
            value={patchTags}
            onChange={(e) => setPatchTags(e.target.value)}
            placeholder={t.memories.tagsInputPlaceholder}
            aria-label={t.memories.tagsInputPlaceholder}
            className={`min-w-[180px] flex-1 ${FIELD_CLASS}`}
          />
        </div>
      )}
    </motion.div>
  )
}
