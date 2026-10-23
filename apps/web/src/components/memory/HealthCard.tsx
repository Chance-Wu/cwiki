import { memo } from 'react'
import { CheckCircle, AlertTriangle, XCircle } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { useHealthSummary } from '../../hooks/useMemories'
import { useHealth } from '../../hooks/useSettings'

function HealthCard() {
  const { t } = useTranslation()
  const { data, isLoading } = useHealthSummary()
  const { data: health } = useHealth()

  if (isLoading || !data) return null

  const { avg_score, distribution } = data

  const scoreColor =
    avg_score >= 0.7 ? 'text-success' : avg_score >= 0.4 ? 'text-brand-500' : 'text-danger'
  const scoreRing =
    avg_score >= 0.7 ? 'stroke-success' : avg_score >= 0.4 ? 'stroke-brand-500' : 'stroke-danger'

  const circumference = 2 * Math.PI * 18
  const dashOffset = circumference * (1 - avg_score)

  return (
    <div className="hidden md:flex items-center gap-3">
      <div className="relative w-9 h-9 shrink-0">
        <svg width="36" height="36" viewBox="0 0 40 40" className="-rotate-90">
          <circle
            cx="20"
            cy="20"
            r="18"
            fill="none"
            strokeWidth="3"
            className="stroke-[var(--border-default)]"
          />
          <circle
            cx="20"
            cy="20"
            r="18"
            fill="none"
            strokeWidth="3"
            strokeLinecap="round"
            className={scoreRing}
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{ transition: 'stroke-dashoffset 0.6s ease' }}
          />
        </svg>
        <span
          className={`absolute inset-0 flex items-center justify-center text-[10px] font-bold tabular-nums ${scoreColor}`}
        >
          {Math.round(avg_score * 100)}
        </span>
      </div>
      <div className="flex flex-col gap-0.5">
        <span className="text-xs font-medium text-[var(--text-secondary)]">
          {t.memories.healthTitle}
        </span>
        <div className="flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
          <span className="flex items-center gap-0.5" title={t.memories.healthHealthy}>
            <CheckCircle size={10} className="text-success" />
            {distribution.healthy}
          </span>
          <span className="flex items-center gap-0.5" title={t.memories.healthReview}>
            <AlertTriangle size={10} className="text-brand-500" />
            {distribution.needs_review}
          </span>
          <span className="flex items-center gap-0.5" title={t.memories.healthSuspicious}>
            <XCircle size={10} className="text-danger" />
            {distribution.suspicious}
          </span>
          {health?.version && (
            <>
              <span className="opacity-40">·</span>
              <span className="font-mono">v{health.version}</span>
            </>
          )}
        </div>
      </div>
      <div className="h-6 w-px bg-[var(--border-default)]" aria-hidden="true" />
    </div>
  )
}

export default memo(HealthCard)
