import { motion, AnimatePresence } from 'framer-motion'
import { Eye } from 'lucide-react'
import MarkdownContent from './MarkdownContent'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { spring } from '../lib/motion'
import { formatTimeShort } from '../lib/format'
import { typeLabel, TYPE_COLORS } from '../lib/labels'
import zh from '../i18n/locales/zh'

type TranslationDict = typeof zh

const QUALITY_LABELS = [
  { value: 0, key: 'q0' },
  { value: 1, key: 'q1' },
  { value: 2, key: 'q2' },
  { value: 3, key: 'q3' },
  { value: 4, key: 'q4' },
  { value: 5, key: 'q5' },
]

interface ReviewItem {
  memory_id: string
  title: string
  content: string
  memory_type: string
  source?: string | null
  confidence?: number | null
  updated_at?: string | null
  ease_factor: number
  interval_days: number
  repetitions: number
  next_review: string
  last_review: string | null
  days_overdue: number
  mastery_level: string
  total_reviews: number
}

export function ReviewCard({
  item,
  showAnswer,
  onShowAnswer,
  t,
  locale,
  maxHeight,
}: {
  item: ReviewItem
  showAnswer: boolean
  onShowAnswer: () => void
  t: TranslationDict
  locale: string
  maxHeight?: string
}) {
  return (
    <Card className="overflow-hidden">
      <div className="px-6 py-5 border-b border-[var(--border-default)]">
        <div className="flex items-center gap-2 mb-3">
          <Badge
            className={`font-semibold uppercase tracking-[0.08em] ${TYPE_COLORS[item.memory_type] ?? 'bg-surface-elevated/50 text-[var(--text-secondary)] border border-[var(--border-default)] shadow-warm-xs'}`}
          >
            {typeLabel(t.common, item.memory_type)}
          </Badge>
          {item.days_overdue > 0 && (
            <Badge variant="danger" className="animate-pulse">
              {t.review.daysOverdue.replace('{n}', String(item.days_overdue))}
            </Badge>
          )}
          {item.source && (
            <span className="ml-auto text-xs text-[var(--text-tertiary)]">
              {item.source}
              {item.updated_at ? ` · ${formatTimeShort(item.updated_at, locale)}` : ''}
            </span>
          )}
        </div>
        <h2 className="text-lg font-semibold text-[var(--text-primary)] break-words leading-snug">
          {item.title}
        </h2>
      </div>

      <div className={`px-6 py-5 overflow-y-auto scrollbar-thin ${maxHeight ?? 'max-h-64'}`}>
        <AnimatePresence mode="wait">
          {showAnswer ? (
            <motion.div
              key="answer"
              initial={{ opacity: 0, rotateX: -15 }}
              animate={{ opacity: 1, rotateX: 0 }}
              exit={{ opacity: 0, rotateX: 15 }}
              transition={spring.gentle}
            >
              <MarkdownContent content={item.content} />
            </motion.div>
          ) : (
            <motion.div
              key="question"
              className="flex flex-col items-center justify-center py-8 gap-3"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={spring.gentle}
            >
              <motion.div
                className="w-14 h-14 rounded-xl flex items-center justify-center bg-surface-elevated/50 border border-[var(--border-default)] shadow-warm-xs transition-all duration-150"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                <Eye size={24} className="text-info-fg" aria-hidden="true" />
              </motion.div>
              <Button variant="ghost" onClick={onShowAnswer} className="text-base font-medium">
                {t.review.showAnswer}
              </Button>
              <p className="text-xs text-[var(--text-tertiary)]">{t.review.flashcardHint}</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="px-6 py-3.5 bg-surface-elevated/40 rounded-lg flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[var(--text-tertiary)] border-t border-[var(--border-default)] font-medium">
        <span className="tabular-nums">EF: {item.ease_factor.toFixed(2)}</span>
        <span className="tabular-nums">
          {t.review.interval}: {item.interval_days}d
        </span>
        <span className="tabular-nums">
          {t.review.repetitions}: {item.repetitions}
        </span>
        {item.last_review && (
          <span>
            {t.review.lastReview}: {formatTimeShort(item.last_review, locale)}
          </span>
        )}
      </div>
    </Card>
  )
}

export function QualityButtons({
  onRate,
  isPending,
  t,
  labelClassName,
  hintClassName,
}: {
  onRate: (quality: number) => void
  isPending: boolean
  t: TranslationDict
  labelClassName?: string
  hintClassName?: string
}) {
  return (
    <div>
      <p
        className={`text-xs mb-3 text-center font-medium ${labelClassName ?? 'text-[var(--text-secondary)]'}`}
      >
        {t.review.rateQuality}
      </p>
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {QUALITY_LABELS.map(({ value, key }, i) => (
          <motion.button
            key={value}
            onClick={() => onRate(value)}
            disabled={isPending}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring.snappy, delay: i * 0.03 }}
            whileHover={{ scale: 1.03, y: -1 }}
            whileTap={{ scale: 0.97 }}
            className={`py-3 sm:py-2.5 rounded-lg text-base font-medium transition-colors duration-150 select-none ring-1 ring-inset ${
              value <= 1
                ? 'bg-danger/18 text-danger-fg hover:bg-danger/25 active:bg-danger/30 ring-danger/30'
                : value <= 3
                  ? 'bg-warning/18 text-warning-fg hover:bg-warning/25 active:bg-warning/30 ring-warning/30'
                  : 'bg-success/18 text-success-fg hover:bg-success/25 active:bg-success/30 ring-success/30'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <div className="text-lg font-semibold">{value}</div>
            <div className="text-xs text-[var(--text-secondary)] mt-0.5">
              {t.review[key as keyof typeof t.review] ?? key}
            </div>
          </motion.button>
        ))}
      </div>
      <p
        className={`text-xs mt-2 text-center font-medium ${hintClassName ?? 'text-[var(--text-tertiary)]'}`}
      >
        {t.review.keyboardHint}
      </p>
    </div>
  )
}
