import { memo } from 'react'
import { Sparkles, TrendingUp, Minus, TrendingDown } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { useCandidateQuality } from '../../hooks/useMemories'

function CandidateQualityCard() {
  const { t } = useTranslation()
  const { data, isLoading } = useCandidateQuality()

  if (isLoading || !data || data.total === 0) return null

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
        <span className="text-xs font-medium text-[var(--text-secondary)] flex items-center gap-1">
          <Sparkles size={10} className="text-brand-500" />
          {t.inbox.qualityTitle}
        </span>
        <div className="flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
          <span className="flex items-center gap-0.5" title={t.inbox.qualityHigh}>
            <TrendingUp size={10} className="text-success" />
            {distribution.high}
          </span>
          <span className="flex items-center gap-0.5" title={t.inbox.qualityMedium}>
            <Minus size={10} className="text-brand-500" />
            {distribution.medium}
          </span>
          <span className="flex items-center gap-0.5" title={t.inbox.qualityLow}>
            <TrendingDown size={10} className="text-danger" />
            {distribution.low}
          </span>
        </div>
      </div>
      <div className="h-6 w-px bg-[var(--border-default)]" aria-hidden="true" />
    </div>
  )
}

export default memo(CandidateQualityCard)
