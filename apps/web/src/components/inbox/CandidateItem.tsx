import { memo } from 'react'
import { motion } from 'framer-motion'
import { AlertTriangle, Undo2 } from 'lucide-react'
import { ease, duration } from '../../lib/motion'
import { useTranslation } from '../../i18n/I18nProvider'
import { type Candidate } from '../../lib/api'
import { typeLabel, TYPE_COLORS } from '../../lib/labels'
import { formatTime } from '../../lib/format'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Checkbox } from '../ui/Checkbox'

function qualityTier(score: number | null): 'high' | 'mid' | 'low' | null {
  if (score == null) return null
  if (score >= 0.7) return 'high'
  if (score >= 0.4) return 'mid'
  return 'low'
}

export interface CandidateItemProps {
  candidate: Candidate
  idx: number
  selected: boolean
  focused: boolean
  navigated: boolean
  showCheckbox: boolean
  onToggle: (id: string) => void
  onOpen: (candidate: Candidate) => void
  /** 已生效列表专用：提供时显示「撤销」按钮（撤销 auto-approve） */
  onRevert?: (candidate: Candidate) => void
}

const CandidateItem = memo(function CandidateItem({
  candidate: c,
  idx,
  selected,
  focused,
  navigated,
  showCheckbox,
  onToggle,
  onOpen,
  onRevert,
}: CandidateItemProps) {
  const { t, locale } = useTranslation()
  return (
    <div
      data-candidate-index={idx}
      className={`candidate-item-enter group bg-transparent px-4 py-3 cursor-pointer relative border-b border-[var(--border-default)] last:border-b-0 hover:bg-brand-badge-bg ${
        selected
          ? 'bg-brand-50/30 border-l-[3px] border-l-brand-400'
          : focused
            ? 'bg-surface-elevated/50 ring-2 ring-inset ring-brand-300'
            : navigated
              ? 'bg-brand-50/25'
              : ''
      }`}
      style={{ animationDelay: `${Math.min(idx * 0.03, 0.3)}s` }}
      onClick={(e) => {
        if ((e.target as HTMLElement).tagName === 'INPUT') return
        e.preventDefault()
        onOpen(c)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(c)
        }
      }}
      role="button"
      tabIndex={0}
    >
      {!selected && !focused && (
        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] rounded-full bg-brand-400 transition-all duration-200 h-5 opacity-0 group-hover:opacity-60 group-hover:h-7" />
      )}
      <div className="flex items-start gap-3">
        {showCheckbox && (
          <span onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={selected}
              onCheckedChange={() => onToggle(c.id)}
              className="mt-0.5"
            />
          </span>
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] break-words leading-snug tracking-[-0.01em]">
              {c.title}
            </h3>
            <div className="flex items-center gap-1.5 shrink-0">
              {c.quality_gate_score != null && (
                <Badge
                  variant={
                    c.quality_gate_score >= 0.7
                      ? 'success'
                      : c.quality_gate_score >= 0.4
                        ? 'warning'
                        : 'danger'
                  }
                  className="tabular-nums px-1.5"
                >
                  {t.inbox.gateScore} {(c.quality_gate_score * 100).toFixed(0)}
                </Badge>
              )}
              {c.confidence !== null && (
                <span className="text-xs text-[var(--text-tertiary)] tabular-nums font-medium">
                  {Math.round(c.confidence * 100)}%
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1 mt-1">
            <Badge
              className={
                TYPE_COLORS[c.type] ||
                'bg-surface-inset text-[var(--text-secondary)] border border-[var(--border-default)] shadow-warm-xs'
              }
            >
              {typeLabel(t.common, c.type)}
            </Badge>
            {c.workspace_name && (
              <Badge variant="success" className="max-w-[120px] truncate">
                {c.workspace_name}
              </Badge>
            )}
            {c.status !== 'pending_review' && (
              <Badge variant={c.status === 'approved' ? 'success' : 'default'}>
                {c.status === 'approved'
                  ? t.inbox.statusApproved
                  : c.status === 'rejected'
                    ? t.inbox.statusRejected
                    : c.status}
              </Badge>
            )}
            {c.value_score !== null && c.value_score >= 0.85 && (
              <Badge variant="danger">{t.inbox.highValue}</Badge>
            )}
            {c.duplicate_probability !== null && (
              <Badge
                variant={
                  c.duplicate_probability >= 0.7
                    ? 'danger'
                    : c.duplicate_probability >= 0.3
                      ? 'warning'
                      : 'success'
                }
                className="gap-1"
              >
                {c.duplicate_probability >= 0.7 && <AlertTriangle size={10} aria-hidden="true" />}
                {t.inbox.similarityLabel} {Math.round(c.duplicate_probability * 100)}%
              </Badge>
            )}
            {onRevert && (
              <span onClick={(e) => e.stopPropagation()}>
                <Button
                  variant="subtle"
                  size="xs"
                  onClick={() => onRevert(c)}
                  className="text-[var(--text-secondary)]"
                >
                  <Undo2 size={11} aria-hidden="true" />
                  {t.inbox.revert}
                </Button>
              </span>
            )}
            {c.updated_at && (
              <span className="text-xs text-[var(--text-tertiary)] ml-auto">
                {formatTime(c.updated_at, locale)}
              </span>
            )}
          </div>
          {/* 质量分数条 */}
          {(c.quality_score != null || c.value_score != null) &&
            (() => {
              const score = c.quality_score ?? c.value_score ?? 0
              const tier = qualityTier(score)
              const gradientClass =
                tier === 'high'
                  ? 'bg-gradient-to-r from-success/40 to-success/55'
                  : tier === 'mid'
                    ? 'bg-gradient-to-r from-warning/40 to-warning/55'
                    : 'bg-gradient-to-r from-danger/40 to-danger/55'
              return tier ? (
                <div className="mt-2 h-1 rounded-full bg-surface-elevated/30 overflow-hidden">
                  <motion.div
                    className={`h-full rounded-full ${gradientClass}`}
                    initial={{ width: 0 }}
                    animate={{ width: `${score * 100}%` }}
                    transition={{ duration: duration.reveal, ease: ease.out }}
                  />
                </div>
              ) : null
            })()}
        </div>
      </div>
    </div>
  )
})

export default CandidateItem
