import { motion } from 'framer-motion'
import { CheckCircle2, Flame } from 'lucide-react'
import { spring } from '../../lib/motion'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { useCountUp } from '../../hooks/useCountUp'

function AnimatedNumber({
  target,
  duration = 800,
  decimals = 0,
  delay = 0,
}: {
  target: number
  duration?: number
  decimals?: number
  delay?: number
}) {
  const ref = useCountUp(target, duration, decimals, delay)
  return <span ref={ref} />
}

interface SessionCompleteProps {
  sessionReviewed: number
  sessionAvgQuality: number | null
  sessionGoodRate: number | null
  sessionStreak: number
  clearSession: () => void
  t: {
    review: {
      sessionComplete: string
      sessionReviewedCount: string
      sessionAccuracy: string
      sessionGoodRate: string
      streak: string
      continueReview: string
    }
  }
}

export const SessionComplete = function SessionComplete({
  sessionReviewed,
  sessionAvgQuality,
  sessionGoodRate,
  sessionStreak,
  clearSession,
  t,
}: SessionCompleteProps) {
  return (
    <motion.div
      className="text-center py-10"
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={spring.gentle}
    >
      <Card className="p-8 md:p-10 max-w-md mx-auto">
        <motion.div
          className="relative flex items-center justify-center w-14 h-14 rounded-xl bg-surface-elevated/50 ring-1 ring-brand-200/25 border border-brand-200/25 shadow-warm-md mx-auto mb-5"
          initial={{ scale: 0, rotate: -20 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ ...spring.snappy, delay: 0.15 }}
        >
          <CheckCircle2 size={28} className="text-success-fg" />
        </motion.div>
        <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-2">
          {t.review.sessionComplete}
        </h2>
        <p className="text-xs text-[var(--text-secondary)] mb-6">
          {t.review.sessionReviewedCount.replace('{n}', String(sessionReviewed))}
        </p>

        {/* 本次会话统计 */}
        {sessionReviewed > 0 && (
          <div
            className={`gap-3 mb-6 ${sessionStreak >= 2 ? 'grid grid-cols-3' : 'grid grid-cols-2'}`}
          >
            <div className="bg-surface-elevated/40 rounded-lg ring-1 ring-subtle p-3.5">
              <div className="text-2xl font-semibold text-[var(--text-primary)] tabular-nums">
                <AnimatedNumber target={sessionAvgQuality ?? 0} decimals={1} delay={200} />
                <span className="text-xs font-normal text-[var(--text-tertiary)] ml-0.5">/5</span>
              </div>
              <div className="text-xs text-[var(--text-secondary)] mt-1 font-medium">
                {t.review.sessionAccuracy}
              </div>
            </div>
            <div className="bg-surface-elevated/40 rounded-lg ring-1 ring-subtle p-3.5">
              <div className="text-2xl font-semibold text-[var(--text-primary)] tabular-nums">
                <AnimatedNumber target={sessionGoodRate ?? 0} delay={350} />
                <span className="text-xs font-normal text-[var(--text-tertiary)] ml-0.5">%</span>
              </div>
              <div className="text-xs text-[var(--text-secondary)] mt-1 font-medium">
                {t.review.sessionGoodRate}
              </div>
            </div>
            {sessionStreak >= 2 && (
              <div className="bg-surface-elevated/40 rounded-lg ring-1 ring-subtle p-3.5">
                <div className="text-2xl font-semibold text-warning-fg tabular-nums flex items-center gap-1.5 justify-center">
                  <Flame size={22} />
                  <AnimatedNumber target={sessionStreak} delay={500} />
                </div>
                <div className="text-xs text-[var(--text-secondary)] mt-1 font-medium">
                  {t.review.streak}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="flex gap-3">
          <Button onClick={clearSession} className="flex-1 text-base">
            {t.review.continueReview}
          </Button>
        </div>
      </Card>
    </motion.div>
  )
}
