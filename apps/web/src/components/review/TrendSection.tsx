import { motion } from 'framer-motion'
import { TrendingUp } from 'lucide-react'
import { spring, ease, duration } from '../../lib/motion'
import { useTranslation } from '../../i18n/I18nProvider'
import { Card } from '../ui/Card'

function TrendChartInner({ data }: { data: Array<{ date: string; count: number }> }) {
  const { locale, t } = useTranslation()
  const maxCount = Math.max(...data.map((d) => d.count), 1)
  const isEmpty = data.every((d) => d.count === 0)

  if (isEmpty) {
    return (
      <div className="flex items-center justify-center h-28 text-sm text-[var(--text-tertiary)]">
        {t.review.noTrendData}
      </div>
    )
  }

  return (
    <div className="flex items-end gap-2 h-28">
      {data.map((d, i) => {
        const height = maxCount > 0 ? Math.max((d.count / maxCount) * 100, d.count > 0 ? 8 : 0) : 0
        const dayLabel = new Date(d.date).toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US', {
          weekday: 'short',
        })
        return (
          <motion.div
            key={d.date}
            className="flex-1 flex flex-col items-center gap-1.5"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring.snappy, delay: 0.3 + i * 0.04 }}
          >
            <span className="text-xs font-medium text-[var(--text-tertiary)] tabular-nums">
              {d.count || ''}
            </span>
            <div className="w-full flex-1 flex items-end">
              <motion.div
                className="w-full bg-gradient-to-t from-brand-500/30 to-brand-400/15 rounded-t-sm hover:from-brand-500/50 hover:to-brand-400/30 transition-colors duration-500"
                initial={{ height: 0 }}
                animate={{ height: `${height}%` }}
                transition={{ duration: duration.reveal, ease: ease.out, delay: 0.4 + i * 0.04 }}
              />
            </div>
            <span className="text-xs text-[var(--text-tertiary)] font-medium">{dayLabel}</span>
          </motion.div>
        )
      })}
    </div>
  )
}

interface TrendSectionProps {
  data: Array<{ date: string; count: number }>
}

export const TrendSection = function TrendSection({ data }: TrendSectionProps) {
  const { t } = useTranslation()

  if (!data.some((d) => d.count > 0)) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay: 0.32 }}
    >
      <Card className="p-4 md:p-5 mb-5">
        <div className="flex items-center gap-2 mb-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-brand-50/25 to-brand-50/10 shrink-0 ring-1 ring-brand-200/40">
            <TrendingUp size={14} className="text-brand-fg" aria-hidden="true" />
          </div>
          <h3 className="text-base font-semibold text-[var(--text-primary)]">
            {t.review.reviewTrendTitle}
          </h3>
          <div className="w-1 h-5 bg-gradient-to-b from-brand/60 to-brand rounded-full ml-1" />
        </div>
        <TrendChartInner data={data} />
      </Card>
    </motion.div>
  )
}
