import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Check,
  X,
  Edit,
  Merge,
  RefreshCw,
  AlertTriangle,
  BarChart3,
  FileText,
  ShieldCheck,
} from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { type Candidate } from '../../lib/api'
import { typeLabel, sourceLabel, TYPE_COLORS, SOURCE_COLORS } from '../../lib/labels'
import { translateBackendReason } from '../../lib/backendReason'
import { formatTime } from '../../lib/format'
import { Dialog } from '../ui/Dialog'
import { Badge } from '../ui/Badge'
import MarkdownContent from '../MarkdownContent'
import { Button } from '../ui/Button'
import { useModal } from '../../hooks/useModal'

const TYPE_REQUIRED_FIELDS: Record<string, string[]> = {
  fact: ['claim', 'context'],
  decision: ['claim', 'context', 'rationale'],
  lesson: ['claim', 'context'],
  issue: ['claim', 'context'],
  convention: ['claim'],
  rule: ['claim'],
  constraint: ['claim', 'context'],
  procedure: ['claim', 'action'],
  pattern: ['claim', 'context'],
  feedback: ['claim'],
  reference: ['claim'],
}

const FIELD_I18N_KEY: Record<string, string> = {
  claim: 'missingFieldClaim',
  context: 'missingFieldContext',
  rationale: 'missingFieldRationale',
  action: 'missingFieldAction',
}

interface DimensionRow {
  label: string
  score: number | null
  key: string
}

interface CandidateDetailModalProps {
  candidate: Candidate | null
  actionLoading: string | null
  onClose: () => void
  onReview: (candidateId: string, action: string) => Promise<void>
  onEdit: (candidate: Candidate) => void
  onMerge: (candidate: Candidate) => void
  onUpdate: (candidate: Candidate) => Promise<void>
  onNavigateToMemory?: (id: string) => void
}

export default function CandidateDetailModal({
  candidate,
  actionLoading,
  onClose,
  onReview,
  onEdit,
  onMerge,
  onUpdate,
  onNavigateToMemory,
}: CandidateDetailModalProps) {
  const { t, locale } = useTranslation()
  useModal(!!candidate, onClose)
  const [confirmAction, setConfirmAction] = useState<string | null>(null)

  const handleClose = useCallback(() => {
    setConfirmAction(null)
    onClose()
  }, [onClose])

  const dimensions: DimensionRow[] = useMemo(() => {
    if (!candidate) return []
    return [
      { key: 'stability', label: t.inbox.qualityDimensionStable, score: candidate.stability },
      { key: 'reusability', label: t.inbox.qualityDimensionReusable, score: candidate.reusability },
      {
        key: 'actionability',
        label: t.inbox.qualityDimensionActionable,
        score: candidate.actionability,
      },
      {
        key: 'scope_confidence',
        label: t.inbox.qualityDimensionScoped,
        score: candidate.scope_confidence,
      },
      {
        key: 'evidence_strength',
        label: t.inbox.qualityDimensionEvidence,
        score: candidate.evidence_strength,
      },
    ]
  }, [candidate, t])

  const missingFields = useMemo(() => {
    if (!candidate?.content_contract) return []
    const contract = candidate.content_contract as Record<string, unknown>
    const required = TYPE_REQUIRED_FIELDS[candidate.type] || []
    return required.filter((f) => {
      const val = contract[f]
      if (!val) return true
      if (typeof val === 'string' && !val.trim()) return true
      if (typeof val === 'object' && val !== null) {
        return !Object.values(val as Record<string, unknown>).some(Boolean)
      }
      return false
    })
  }, [candidate])

  const evidenceRefs = useMemo(() => {
    if (!candidate?.content_contract) return []
    const contract = candidate.content_contract as Record<string, unknown>
    return (contract.evidence_refs as Array<Record<string, string>>) || []
  }, [candidate])

  const relationDecision = useMemo(() => {
    if (!candidate?.relation_decision) return null
    return candidate.relation_decision as Record<string, unknown>
  }, [candidate])

  // 键盘快捷键：a=采纳、r=拒绝、e=编辑（仅在无待确认操作时生效，避免误触）
  useEffect(() => {
    if (!candidate || confirmAction) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'a') {
        e.preventDefault()
        setConfirmAction('approve')
      } else if (e.key === 'r') {
        e.preventDefault()
        setConfirmAction('reject')
      } else if (e.key === 'e') {
        e.preventDefault()
        onEdit(candidate)
        handleClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [candidate, confirmAction, onEdit, handleClose])

  return (
    <Dialog
      open={!!candidate}
      onOpenChange={(o) => {
        if (!o) handleClose()
      }}
      title={candidate?.title ?? ''}
      size="xl"
      fixedHeight
      footer={
        candidate && (
          <div
            key={confirmAction ? 'confirm' : 'actions'}
            className="flex flex-wrap gap-2 animate-[fade-in_0.15s_ease-out]"
          >
            {confirmAction ? (
              <>
                <span className="text-sm text-[var(--text-secondary)] flex items-center">
                  {confirmAction === 'approve' && t.inbox.confirmApprove}
                  {confirmAction === 'reject' && t.inbox.confirmReject}
                  {confirmAction === 'update' && t.inbox.confirmUpdate}
                </span>
                <div className="ml-auto flex gap-2">
                  <Button variant="secondary" size="sm" onClick={() => setConfirmAction(null)}>
                    {t.common.cancel}
                  </Button>
                  <Button
                    variant={
                      confirmAction === 'reject'
                        ? 'danger'
                        : confirmAction === 'update'
                          ? 'warning'
                          : 'success'
                    }
                    size="sm"
                    onClick={async () => {
                      if (confirmAction === 'approve') {
                        await onReview(candidate.id, 'approve')
                        handleClose()
                      } else if (confirmAction === 'reject') {
                        await onReview(candidate.id, 'reject')
                        handleClose()
                      } else if (confirmAction === 'update') {
                        await onUpdate(candidate)
                        handleClose()
                      }
                      setConfirmAction(null)
                    }}
                    disabled={actionLoading === candidate.id}
                  >
                    {t.common.confirm}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setConfirmAction('reject')}
                  title={`${t.inbox.reject} (R)`}
                >
                  <X size={14} aria-hidden="true" /> {t.inbox.reject}
                  <kbd className="border border-[var(--border-default)] shadow-warm-xs ml-1 px-1 py-0.5 text-3xs font-mono bg-surface-inset rounded-lg">
                    R
                  </kbd>
                </Button>
                <div className="ml-auto flex flex-wrap items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      onEdit(candidate)
                      handleClose()
                    }}
                    title={`${t.inbox.edit} (E)`}
                  >
                    <Edit size={14} aria-hidden="true" /> {t.inbox.edit}
                    <kbd className="border border-[var(--border-default)] shadow-warm-xs ml-1 px-1 py-0.5 text-3xs font-mono bg-surface-inset rounded-lg">
                      E
                    </kbd>
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      onMerge(candidate)
                      handleClose()
                    }}
                  >
                    <Merge size={14} aria-hidden="true" /> {t.inbox.merge}
                  </Button>
                  {candidate.similar_memory_id && candidate.similar_memory_source === 'memory' && (
                    <Button variant="ghost" size="sm" onClick={() => setConfirmAction('update')}>
                      <RefreshCw size={14} aria-hidden="true" /> {t.inbox.update}
                    </Button>
                  )}
                  <Button
                    variant="success"
                    size="sm"
                    onClick={() => setConfirmAction('approve')}
                    title={`${t.inbox.approve} (A)`}
                  >
                    <Check size={14} aria-hidden="true" /> {t.inbox.approve}
                    <kbd className="border border-[var(--border-default)] shadow-warm-xs ml-1 px-1 py-0.5 text-3xs font-mono bg-surface-inset rounded-lg">
                      A
                    </kbd>
                  </Button>
                </div>
              </>
            )}
          </div>
        )
      }
    >
      {candidate && (
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
          <div className="flex flex-wrap items-center gap-4 mb-4 text-sm text-[var(--text-tertiary)]">
            <Badge className={TYPE_COLORS[candidate.type] || ''}>
              {typeLabel(t.common, candidate.type)}
            </Badge>
            <Badge className={SOURCE_COLORS[candidate.source] || ''}>
              {sourceLabel(t.common, candidate.source)}
            </Badge>
            {candidate.workspace_name && (
              <Badge variant="success" className="max-w-[120px] truncate">
                {candidate.workspace_name}
              </Badge>
            )}
            {candidate.value_score !== null && candidate.value_score >= 0.85 && (
              <Badge variant="danger">{t.inbox.highValue}</Badge>
            )}
            {candidate.updated_at && <span>{formatTime(candidate.updated_at, locale)}</span>}
          </div>

          {/* 质量诊断面板 */}
          {(candidate.quality_gate_score !== null || candidate.quality_gate_reason) && (
            <div className="mb-4 p-3 rounded-lg border border-[var(--border-default)] bg-surface-inset">
              <div className="flex items-center gap-2 mb-2">
                <BarChart3 size={14} className="text-[var(--text-secondary)]" />
                <span className="text-sm font-medium text-[var(--text-primary)]">
                  {t.inbox.qualityDiagnostics}
                </span>
                {candidate.quality_gate_score !== null && (
                  <Badge
                    variant={
                      candidate.quality_gate_score >= 0.7
                        ? 'success'
                        : candidate.quality_gate_score >= 0.4
                          ? 'warning'
                          : 'danger'
                    }
                  >
                    {t.inbox.gateScore}: {Math.round(candidate.quality_gate_score * 100)}
                  </Badge>
                )}
              </div>
              {/* 五维无数据时收起条形区：仅剩 gate 分与原因，避免整排 "—" 占位 */}
              {dimensions.some((dim) => dim.score !== null) && (
                <div className="space-y-1.5">
                  {dimensions.map((dim) => (
                    <div key={dim.key} className="flex items-center gap-2 text-xs">
                      <span className="w-20 text-[var(--text-secondary)]">{dim.label}</span>
                      <div className="flex-1 h-1.5 bg-[var(--border-default)] rounded-full overflow-hidden">
                        {dim.score !== null ? (
                          <div
                            className={`h-full rounded-full transition-all ${dim.score >= 0.7 ? 'bg-success-fg' : dim.score >= 0.4 ? 'bg-warning-fg' : 'bg-danger-fg'}`}
                            style={{ width: `${Math.round(dim.score * 100)}%` }}
                          />
                        ) : (
                          <div className="h-full w-0" />
                        )}
                      </div>
                      <span className="w-10 text-right tabular-nums text-[var(--text-tertiary)]">
                        {dim.score !== null ? Math.round(dim.score * 100) : '—'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {candidate.quality_gate_reason && (
                <div className="mt-2 pt-2 border-t border-[var(--border-default)]">
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                    {translateBackendReason(candidate.quality_gate_reason, t, locale)}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* 完整性检查 */}
          {candidate.content_contract && (
            <div
              className={`mb-4 p-3 rounded-lg border ${missingFields.length === 0 ? 'bg-success-bg border-success-border' : 'bg-warning-bg border-warning-border'}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <ShieldCheck
                  size={14}
                  className={missingFields.length === 0 ? 'text-success-fg' : 'text-warning-fg'}
                />
                <span
                  className={`text-sm font-medium ${missingFields.length === 0 ? 'text-success-fg' : 'text-warning-fg'}`}
                >
                  {t.inbox.completenessCheck}
                </span>
              </div>
              {missingFields.length === 0 ? (
                <p className="text-xs text-success-fg">
                  {t.inbox.completenessPass.replace('{type}', typeLabel(t.common, candidate.type))}
                </p>
              ) : (
                <div className="text-xs text-warning-fg">
                  <p className="mb-1">{t.inbox.completenessMissing}:</p>
                  <ul className="list-disc list-inside space-y-0.5">
                    {missingFields.map((f) => (
                      <li key={f}>{t.inbox[FIELD_I18N_KEY[f] as keyof typeof t.inbox] || f}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* 来源证据 */}
          {evidenceRefs.length > 0 && (
            <div className="mb-4 p-3 rounded-lg border border-info-border bg-info-bg">
              <div className="flex items-center gap-2 mb-2">
                <FileText size={14} className="text-info-fg" />
                <span className="text-sm font-medium text-info-fg">{t.inbox.evidenceSection}</span>
                <Badge variant="info">{evidenceRefs.length}</Badge>
              </div>
              <ul className="space-y-1.5">
                {evidenceRefs.map((ref, i) => (
                  <li key={i} className="text-xs text-[var(--text-secondary)]">
                    {ref.source_ref && (
                      <span className="font-mono text-info-fg">{ref.source_ref}</span>
                    )}
                    {ref.supports && (
                      <span className="ml-2 text-[var(--text-tertiary)]">— {ref.supports}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {candidate.duplicate_probability !== null &&
            candidate.duplicate_probability >= 0.6 &&
            candidate.similar_memory_id && (
              <div
                className={`mb-4 p-3 rounded-lg border ${candidate.duplicate_probability >= 0.85 ? 'bg-danger-bg border-danger-border' : candidate.duplicate_probability >= 0.7 ? 'bg-warning-bg border-warning-border' : 'bg-info-bg border-info-border'}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <AlertTriangle
                    size={14}
                    className={
                      candidate.duplicate_probability >= 0.85
                        ? 'text-danger-fg'
                        : candidate.duplicate_probability >= 0.7
                          ? 'text-warning-fg'
                          : 'text-info-fg'
                    }
                  />
                  <span
                    className={`text-sm font-medium ${candidate.duplicate_probability >= 0.85 ? 'text-danger-fg' : candidate.duplicate_probability >= 0.7 ? 'text-warning-fg' : 'text-info-fg'}`}
                  >
                    {t.inbox.similarTo} (
                    <span className="tabular-nums">
                      {Math.round(candidate.duplicate_probability * 100)}
                    </span>
                    %)
                  </span>
                  {candidate.similar_memory_relation && (
                    <Badge
                      variant={
                        candidate.similar_memory_relation === 'DUPLICATE'
                          ? 'danger'
                          : candidate.similar_memory_relation === 'MERGE'
                            ? 'info'
                            : candidate.similar_memory_relation === 'UPDATE'
                              ? 'warning'
                              : 'danger'
                      }
                    >
                      {t.inbox[
                        `relation_${candidate.similar_memory_relation.toLowerCase()}` as keyof typeof t.inbox
                      ] || candidate.similar_memory_relation}
                    </Badge>
                  )}
                </div>
                <button
                  type="button"
                  className="text-left w-full group"
                  aria-label={candidate.similar_memory_title || t.inbox.similarMemory}
                  onClick={() => {
                    if (candidate.similar_memory_id) {
                      onNavigateToMemory?.(candidate.similar_memory_id)
                      handleClose()
                    }
                  }}
                >
                  <p className="text-sm text-[var(--text-secondary)] mt-1 font-medium">
                    {candidate.similar_memory_title && (
                      <span className="truncate block group-hover:text-brand-500 transition-colors">
                        {candidate.similar_memory_title}
                      </span>
                    )}
                    <span className="text-[var(--text-tertiary)] font-mono text-xs group-hover:text-brand-500/70 transition-colors">
                      {candidate.similar_memory_source === 'candidate'
                        ? t.inbox.similarCandidate
                        : t.inbox.similarMemory}{' '}
                      ID: {candidate.similar_memory_id.slice(0, 8)}...
                    </span>
                  </p>
                </button>
                {relationDecision && (
                  <div className="mt-2 pt-2 border-t border-current/10">
                    <p className="text-xs font-medium mb-0.5 opacity-80">
                      {t.inbox.relationReasoning}:
                    </p>
                    <p className="text-xs opacity-70 leading-relaxed">
                      {(relationDecision.reason as string) || JSON.stringify(relationDecision)}
                    </p>
                  </div>
                )}
              </div>
            )}
          <div className="mt-5">
            <MarkdownContent content={candidate.content} />
          </div>
        </div>
      )}
    </Dialog>
  )
}
