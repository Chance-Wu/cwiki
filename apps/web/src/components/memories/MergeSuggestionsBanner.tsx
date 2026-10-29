import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { spring } from '../../lib/motion'
import { Merge, X, Loader2, CheckSquare, Square, AlertCircle } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { type MergeSuggestion } from '../../lib/api'
import { Button } from '../ui/Button'
import { getSimilarityColor } from '../../lib/utils/similarity'

interface MergeSuggestionsBannerProps {
  suggestions: MergeSuggestion[]
  generatedAt: string | null
  consolidatePending: boolean
  strategy?: string
  onConsolidate: () => void
  onOpenMerge: (s: MergeSuggestion) => void
  onBatchMerge?: (suggestions: MergeSuggestion[]) => void
  onDismissSuggestion?: (s: MergeSuggestion) => void
}

/** 合并建议横幅：展示相似记忆对，可整条关闭（纯 UI 状态内聚在此）。 */
export default function MergeSuggestionsBanner({
  suggestions,
  generatedAt,
  consolidatePending,
  strategy,
  onConsolidate,
  onOpenMerge,
  onBatchMerge,
  onDismissSuggestion,
}: MergeSuggestionsBannerProps) {
  const { t } = useTranslation()
  const [dismissed, setDismissed] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showBatchConfirm, setShowBatchConfirm] = useState(false)

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (dismissed) return

      // Ctrl/Cmd + A: Select all
      if ((e.ctrlKey || e.metaKey) && e.key === 'a' && onBatchMerge) {
        e.preventDefault()
        toggleSelectAll()
      }

      // Ctrl/Cmd + Enter: Batch merge (when items selected)
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && selectedIds.size > 0 && onBatchMerge) {
        e.preventDefault()
        handleBatchMerge()
      }

      // Escape: Dismiss banner
      if (e.key === 'Escape' && !showBatchConfirm) {
        setDismissed(true)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [dismissed, selectedIds, showBatchConfirm, onBatchMerge])

  if (dismissed || suggestions.length === 0) return null

  const toggleSelect = (id: string) => {
    const newSet = new Set(selectedIds)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    setSelectedIds(newSet)
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === suggestions.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(suggestions.map((s) => s.source_id)))
    }
  }

  const handleBatchMerge = () => {
    const selected = suggestions.filter((s) => selectedIds.has(s.source_id))
    if (onBatchMerge && selected.length > 0) {
      setShowBatchConfirm(true)
    }
  }

  const confirmBatchMerge = () => {
    const selected = suggestions.filter((s) => selectedIds.has(s.source_id))
    if (onBatchMerge && selected.length > 0) {
      onBatchMerge(selected)
      setSelectedIds(new Set())
      setShowBatchConfirm(false)
    }
  }

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        className="mb-5 p-4 bg-warning-bg border border-warning-border rounded-lg shadow-warm-sm"
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1.5">
              <Merge size={14} className="text-warning-fg" aria-hidden="true" />
              <span className="text-sm font-semibold text-warning-fg">
                {t.memories.mergeSuggestions}
              </span>
            </div>
            {strategy && (
              <span className="text-xs font-medium text-warning-fg px-2 py-0.5 bg-warning/15 rounded-full border border-warning/20">
                {strategy}
              </span>
            )}
            {generatedAt && (
              <span className="text-xs text-warning-fg/60">
                {new Date(generatedAt).toLocaleString()}
              </span>
            )}
            <span className="text-xs text-warning-fg/60">
              {suggestions.length === 1
                ? t.memories.pairCountOne
                : t.memories.pairCount.replace('{n}', String(suggestions.length))}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {onBatchMerge && selectedIds.size > 0 && (
              <Button
                onClick={handleBatchMerge}
                variant="warning"
                size="xs"
                className="shadow-warm-xs"
              >
                <Merge size={14} />
                {t.memories.batchMerge} ({selectedIds.size})
              </Button>
            )}
            <Button
              onClick={onConsolidate}
              disabled={consolidatePending}
              variant="warning"
              size="xs"
              title="Refresh suggestions"
            >
              <Loader2 size={14} className={consolidatePending ? 'animate-spin' : ''} />
              {t.common.refresh}
            </Button>
            <Button
              onClick={() => setDismissed(true)}
              variant="icon"
              size="sm"
              title={t.common.close}
              className="hover:bg-warning/20"
            >
              <X size={16} aria-hidden="true" />
            </Button>
          </div>
        </div>

        {/* Select All */}
        {onBatchMerge && suggestions.length > 1 && (
          <div className="mb-3 flex items-center gap-2 pb-2 border-b border-warning/15">
            <button
              onClick={toggleSelectAll}
              className="text-xs text-warning-fg hover:text-warning-fg/80 flex items-center gap-1.5 transition-colors"
            >
              {selectedIds.size === suggestions.length ? (
                <CheckSquare size={14} className="text-warning-fg" />
              ) : (
                <Square size={14} />
              )}
              <span className="font-medium">{t.common.selectAll}</span>
            </button>
            {selectedIds.size > 0 && (
              <span className="text-xs text-warning-fg/60">
                {t.memories.selectedCount.replace('{n}', String(selectedIds.size))}
              </span>
            )}
          </div>
        )}

        {/* Suggestions List */}
        <div className="space-y-1.5">
          <AnimatePresence mode="popLayout">
            {suggestions.map((s, i) => {
              const isSelected = selectedIds.has(s.source_id)
              const similarityPercent = Math.round(s.similarity * 100)
              const similarityColor = getSimilarityColor(s.similarity)

              return (
                <motion.div
                  key={`${s.source_id}-${s.target_id}`}
                  layout
                  initial={{ opacity: 0, y: 8, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{
                    type: 'spring',
                    ...spring.gentle,
                    delay: Math.min(i * 0.05, 0.3),
                  }}
                  className={`relative flex items-center gap-3 bg-white dark:bg-[var(--surface-default)] border rounded-lg px-3 py-2.5 transition-all duration-200 cursor-pointer group ${
                    isSelected
                      ? 'border-warning/50 ring-2 ring-warning/30 shadow-warm-xs'
                      : 'border-warning/15 hover:border-warning/30 hover:shadow-warm-xs'
                  }`}
                  onClick={() => onBatchMerge && toggleSelect(s.source_id)}
                >
                  {/* Checkbox */}
                  {onBatchMerge && (
                    <div className="shrink-0">
                      {isSelected ? (
                        <CheckSquare
                          size={16}
                          className="text-warning-fg transition-transform group-hover:scale-110"
                        />
                      ) : (
                        <Square
                          size={16}
                          className="text-[var(--text-tertiary)] group-hover:text-warning-fg/60 transition-colors"
                        />
                      )}
                    </div>
                  )}

                  {/* Content */}
                  <div className="min-w-0 flex-1 flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 text-sm">
                        <span className="text-[var(--text-primary)] font-medium truncate">
                          {s.source_title}
                        </span>
                        <span className="text-[var(--text-tertiary)] shrink-0">→</span>
                        <span className="text-[var(--text-primary)] truncate">
                          {s.target_title}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Similarity Badge */}
                  <div
                    className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-semibold tabular-nums ${similarityColor}`}
                  >
                    {similarityPercent}%
                  </div>

                  {/* Merge Button */}
                  <Button
                    onClick={(e) => {
                      e.stopPropagation()
                      onOpenMerge(s)
                    }}
                    variant="subtle"
                    size="xs"
                    className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    {t.memories.mergeAction}
                  </Button>

                  {/* Dismiss Button */}
                  {onDismissSuggestion && (
                    <Button
                      onClick={(e) => {
                        e.stopPropagation()
                        onDismissSuggestion(s)
                      }}
                      variant="icon"
                      size="xs"
                      title="忽略此建议（不再提示）"
                      className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                    >
                      <X size={14} aria-hidden="true" />
                    </Button>
                  )}
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
      </motion.div>

      {/* Batch Merge Confirmation Dialog */}
      <AnimatePresence>
        {showBatchConfirm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={() => setShowBatchConfirm(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-[var(--surface-default)] border border-[var(--border-default)] rounded-lg shadow-warm-lg max-w-md w-full p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start gap-3 mb-4">
                <div className="shrink-0 w-10 h-10 rounded-full bg-warning/15 flex items-center justify-center">
                  <AlertCircle size={20} className="text-warning-fg" />
                </div>
                <div className="flex-1">
                  <h3 className="text-base font-semibold text-[var(--text-primary)] mb-1">
                    {t.memories.batchMergeConfirmTitle}
                  </h3>
                  <p className="text-sm text-[var(--text-secondary)]">
                    {t.memories.batchMergeConfirmDesc.replace('{n}', String(selectedIds.size))}
                  </p>
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <Button onClick={() => setShowBatchConfirm(false)} variant="secondary" size="sm">
                  {t.common.cancel}
                </Button>
                <Button onClick={confirmBatchMerge} variant="warning" size="sm">
                  <Merge size={14} />
                  {t.memories.batchMerge}
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
