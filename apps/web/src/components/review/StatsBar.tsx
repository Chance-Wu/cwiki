import { motion } from 'framer-motion'
import { AlertCircle, Calendar, CheckCircle2, Clock } from 'lucide-react'
import { spring } from '../../lib/motion'
import { useTranslation } from '../../i18n/I18nProvider'
import StatCard from '../StatCard'

interface StatsBarProps {
  dueNow: number
  dueToday: number
  reviewedToday: number
  totalScheduled: number
  sessionReviewed: number
}

export const StatsBar = function StatsBar({
  dueNow,
  dueToday,
  reviewedToday,
  totalScheduled,
  sessionReviewed,
}: StatsBarProps) {
  const { t } = useTranslation()

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5 mb-6 md:mb-8">
      {[
        <StatCard
          key="due-now"
          label={t.review.dueNow}
          value={dueNow}
          Icon={AlertCircle}
          tone="danger"
        />,
        <StatCard
          key="due-today"
          label={t.review.dueToday}
          value={dueToday}
          Icon={Calendar}
          tone="warning"
        />,
        <StatCard
          key="reviewed"
          label={t.review.reviewedToday}
          value={reviewedToday + sessionReviewed}
          Icon={CheckCircle2}
          tone="success"
        />,
        <StatCard
          key="scheduled"
          label={t.review.totalScheduled}
          value={totalScheduled}
          Icon={Clock}
          tone="info"
        />,
      ].map((card, i) => (
        <motion.div
          key={card.key}
          initial={{ opacity: 0, y: 14, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ ...spring.snappy, delay: i * 0.06 }}
        >
          {card}
        </motion.div>
      ))}
    </div>
  )
}
