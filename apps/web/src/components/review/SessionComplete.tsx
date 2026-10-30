import { motion } from 'framer-motion'
import { CheckCircle2, Flame } from 'lucide-react'
import { spring } from '../../lib/motion'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { useCountUp } from '../../hooks/useCountUp'
import { MASTERY_COLORS } from '../../lib/labels'
import { formatClock } from './reviewSessionUtils'

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

interface SessionResult {
  title: string
  quality: number
  prevMastery: string | null
  newMastery: string
}

interface SessionCompleteProps {
  sessionReviewed: number
  sessionAvgQuality: number | null
  sessionGoodRate: number | null
  sessionStreak: number
  clearSession: () => void
  results?: SessionResult[]
  elapsedSec?: number
  goal?: number
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
  results = [],
  elapsedSec = 0,
  goal,
  t,
}: SessionCompleteProps) {
  const tr = t.review as unknown as Record<string, string>
  const goalReached = goal !== undefined && goal > 0 && sessionReviewed >= goal
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
          {elapsedSec > 0 && (
            <span className="text-[var(--text-tertiary)]">
              {' · '}
              {tr.elapsedTime} {formatClock(elapsedSec)}
            </span>
          )}
          {goalReached && (
            <span className="font-medium text-success-fg">
              {' · '}
              {tr.goalReached}
            </span>
          )}
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

        {/* 本轮逐条结果 */}
        {results.length > 0 && (
          <div className="mb-6 text-left">
            <div className="mb-2 text-xs font-medium text-[var(--text-secondary)]">
              {tr.sessionResults}
            </div>
            <ul className="max-h-56 space-y-1.5 overflow-y-auto scrollbar-thin pr-1">
              {results.map((r, i) => (
                <li
                  key={`${r.title}-${i}`}
                  className="flex items-center gap-2 rounded-lg border border-[var(--border-default)] bg-surface-elevated/30 px-2.5 py-1.5"
                >
                  <span
                    className="min-w-0 flex-1 truncate text-xs text-[var(--text-primary)]"
                    title={r.title}
                  >
                    {r.title}
                  </span>
                  {r.prevMastery && r.prevMastery !== r.newMastery && (
                    <Badge
                      className={`hidden sm:inline-flex ${MASTERY_COLORS[r.prevMastery] ?? ''}`}
                    >
                      {tr[`mastery_${r.prevMastery}`] ?? r.prevMastery}
                    </Badge>
                  )}
                  <Badge
                    className={
                      MASTERY_COLORS[r.newMastery] ??
                      'bg-surface-elevated/40 text-[var(--text-secondary)] border border-[var(--border-default)]'
                    }
                  >
                    {tr[`mastery_${r.newMastery}`] ?? r.newMastery}
                  </Badge>
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-2xs font-semibold tabular-nums ${
                      r.quality >= 4
                        ? 'text-success-fg'
                        : r.quality <= 1
                          ? 'text-danger-fg'
                          : 'text-warning-fg'
                    }`}
                  >
                    {r.quality}
                  </span>
                </li>
              ))}
            </ul>
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
