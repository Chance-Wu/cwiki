import { motion } from 'framer-motion'
import { Brain } from 'lucide-react'
import { spring, ease, duration } from '../../lib/motion'
import { useTranslation } from '../../i18n/I18nProvider'
import { Card } from '../ui/Card'

const MASTERY_ORDER = ['new', 'learning', 'familiar', 'proficient', 'mastered'] as const

const MASTERY_BAR_COLORS: Record<string, string> = {
  new: 'bg-[var(--border-strong)]',
  learning: 'bg-danger',
  familiar: 'bg-warning',
  proficient: 'bg-info',
  mastered: 'bg-success',
}

function MasteryBarInner({
  distribution,
  total,
}: {
  distribution: Record<string, number>
  total: number
}) {
  const { t } = useTranslation()

  return (
    <div className="space-y-2">
      {MASTERY_ORDER.map((level, i) => {
        const count = distribution[level] ?? 0
        const pct = total > 0 ? Math.round((count / total) * 100) : 0
        const barWidth = total > 0 ? Math.max((count / total) * 100, count > 0 ? 4 : 0) : 0
        return (
          <motion.div
            key={level}
            className="flex items-center gap-3"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ ...spring.snappy, delay: 0.3 + i * 0.04 }}
          >
            <div className="flex items-center gap-1.5 w-14 justify-end">
              <span
                className={`w-1.5 h-1.5 rounded-full ${MASTERY_BAR_COLORS[level] ?? 'bg-[var(--border-strong)]'} opacity-80`}
              />
              <span className="text-xs font-medium text-[var(--text-secondary)]">
                {t.review[`mastery_${level}` as keyof typeof t.review] ?? level}
              </span>
            </div>
            <div className="flex-1 h-1.5 bg-surface-inset rounded-full overflow-hidden border border-[var(--border-default)]">
              <motion.div
                className={`h-full rounded-full ${MASTERY_BAR_COLORS[level] ?? 'bg-[var(--border-strong)]'}`}
                initial={{ width: 0 }}
                animate={{ width: `${barWidth}%` }}
                transition={{ duration: duration.reveal, ease: ease.out, delay: 0.4 + i * 0.04 }}
              />
            </div>
            <span className="text-xs text-[var(--text-secondary)] w-16 text-right tabular-nums font-medium">
              {count} <span className="text-[var(--text-tertiary)]">({pct}%)</span>
            </span>
          </motion.div>
        )
      })}
    </div>
  )
}

interface MasterySectionProps {
  distribution: Record<string, number>
  total: number
}

export const MasterySection = function MasterySection({
  distribution,
  total,
}: MasterySectionProps) {
  const { t } = useTranslation()

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay: 0.24 }}
    >
      <Card className="p-4 md:p-5 mb-5">
        <div className="flex items-center gap-2 mb-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-info/20 to-info/10 shrink-0 ring-1 ring-info/30">
            <Brain size={14} className="text-info-fg" aria-hidden="true" />
          </div>
          <h3 className="text-base font-semibold text-[var(--text-primary)]">
            {t.review.masteryTitle}
          </h3>
          <div className="w-1 h-5 bg-gradient-to-b from-info/60 to-info rounded-full ml-1" />
        </div>
        <MasteryBarInner distribution={distribution} total={total} />
      </Card>
    </motion.div>
  )
}
