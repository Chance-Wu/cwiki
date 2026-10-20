import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { spring, duration } from '../../lib/motion'
import { Lightbulb, Clock, AlertTriangle, BookOpen, ArrowRight } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { typeLabel, MASTERY_COLORS } from '../../lib/labels'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { Button } from '../ui/Button'
import { useToast } from '../Toast'
import { useLearningSuggestions } from '../../hooks/useDashboard'
import { useReviewStats, useDueReviews } from '../../hooks/useReview'
import { Badge } from '../ui/Badge'
import { Card } from '../ui/Card'

const MotionLink = motion.create(Link)

export default function LearningPanel({ workspaceId }: { workspaceId?: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [processing, setProcessing] = useState<Set<string>>(new Set())

  const suggestionsQuery = useLearningSuggestions(workspaceId)
  const reviewStatsQuery = useReviewStats()
  const dueReviewsQuery = useDueReviews(5)

  const handleDeprecate = async (memoryId: string) => {
    setProcessing((prev) => new Set(prev).add(memoryId))
    try {
      await api.applyMemoryUpdate(memoryId, { status: 'deprecated' })
      queryClient.invalidateQueries()
      toast(t.common.success, 'success')
    } catch {
      toast(t.home.actionFailed, 'error')
    } finally {
      setProcessing((prev) => {
        const next = new Set(prev)
        next.delete(memoryId)
        return next
      })
    }
  }

  const handleConfirmConfidence = async (memoryId: string) => {
    setProcessing((prev) => new Set(prev).add(memoryId))
    try {
      await api.applyMemoryUpdate(memoryId, { confidence: 0.8 })
      queryClient.invalidateQueries()
      toast(t.common.success, 'success')
    } catch {
      toast(t.home.actionFailed, 'error')
    } finally {
      setProcessing((prev) => {
        const next = new Set(prev)
        next.delete(memoryId)
        return next
      })
    }
  }

  const suggestions = suggestionsQuery.data
  const hasSuggestions = suggestions && suggestions.total_suggestions > 0
  const hasDueReviews =
    (reviewStatsQuery.data?.due_now ?? 0) > 0 &&
    dueReviewsQuery.data != null &&
    dueReviewsQuery.data.length > 0

  if (!hasSuggestions && !hasDueReviews) return null

  // 仅两类建议（过时 / 低置信）时半栏两列排得开；单一分区时一列铺满
  const suggestionSectionCount = [
    suggestions?.stale?.length,
    suggestions?.low_confidence?.length,
  ].filter((count) => (count ?? 0) > 0).length
  const suggestionGridColumns = suggestionSectionCount >= 2 ? 'md:grid-cols-2' : 'md:grid-cols-1'

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay: 0.4 }}
      className="flex min-w-0 flex-1"
    >
      <Card className="flex min-w-0 flex-1 flex-col p-5 md:p-6">
        {/* ═══ 分区一：学习助手（过时记忆 / 低置信建议，不含新建入口） ═══ */}
        {hasSuggestions && (
          <>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-warning/25 to-warning/10 shrink-0 ring-1 ring-warning/30 border border-warning/25 shadow-warm-xs">
                <Lightbulb size={15} className="text-warning-fg" aria-hidden="true" />
              </div>
              <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">
                {t.home.learningAssistant}
              </h3>
              <div className="w-1 h-5 bg-gradient-to-b from-warning/60 to-warning rounded-full ml-1" />
              <span className="ml-auto px-2.5 py-0.5 bg-warning/22 text-warning-fg text-sm font-semibold rounded-lg tabular-nums border border-warning/35 shadow-warm-xs">
                {suggestions.total_suggestions}
              </span>
            </div>
            <p className="text-xs text-[var(--text-secondary)] mb-4 ml-12 font-medium">
              {t.home.learningSubtitle}
            </p>

            <div className={`grid grid-cols-1 ${suggestionGridColumns} gap-4`}>
              {(suggestions.stale?.length ?? 0) > 0 && (
                <div className="bg-warning-subtle-bg rounded-2xl p-4 border border-warning-subtle-border transition-all duration-150 hover:bg-warning-subtle-hover">
                  <div className="flex items-center gap-2 mb-3">
                    <Clock size={14} className="text-warning-fg" aria-hidden="true" />
                    <h4 className="text-sm font-semibold text-warning-fg">
                      {t.home.staleMemories}
                    </h4>
                    <span className="ml-auto text-sm text-warning-fg font-semibold tabular-nums">
                      {suggestions.stale.length}
                    </span>
                  </div>
                  <p className="text-xs text-warning-fg/80 mb-3 font-medium">{t.home.staleHint}</p>
                  <div className="space-y-3">
                    {suggestions.stale.slice(0, 3).map((item, i) => (
                      <motion.div
                        key={item.memory_id}
                        className="flex items-center gap-2 text-sm group"
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.5 + i * 0.08, duration: duration.stagger }}
                      >
                        <span className="text-[var(--text-secondary)] truncate flex-1 min-w-0 font-medium">
                          {item.title}
                        </span>
                        <span className="text-warning-fg text-xs shrink-0 font-semibold">
                          {typeLabel(t.common, item.type)}
                        </span>
                        <Button
                          onClick={() => handleDeprecate(item.memory_id)}
                          disabled={processing.has(item.memory_id)}
                          variant="ghost"
                          size="xs"
                          className="text-warning-fg hover:bg-warning/10 md:opacity-0 md:group-hover:opacity-100"
                        >
                          {processing.has(item.memory_id) ? t.common.loading : t.home.deprecate}
                        </Button>
                      </motion.div>
                    ))}
                  </div>
                </div>
              )}

              {(suggestions.low_confidence?.length ?? 0) > 0 && (
                <div className="bg-danger-subtle-bg rounded-2xl p-4 border border-danger-subtle-border transition-all duration-150 hover:bg-danger-subtle-hover">
                  <div className="flex items-center gap-2 mb-3">
                    <AlertTriangle size={14} className="text-danger-fg" aria-hidden="true" />
                    <h4 className="text-sm font-semibold text-danger-fg">{t.home.lowConfidence}</h4>
                    <span className="ml-auto text-sm text-danger-fg font-semibold tabular-nums">
                      {suggestions.low_confidence.length}
                    </span>
                  </div>
                  <p className="text-xs text-danger-fg/80 mb-3 font-medium">{t.home.lowConfHint}</p>
                  <div className="space-y-3">
                    {suggestions.low_confidence.slice(0, 3).map((item, i) => (
                      <motion.div
                        key={item.memory_id}
                        className="flex items-center gap-2 text-sm group"
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.5 + i * 0.08, duration: duration.stagger }}
                      >
                        <span className="text-[var(--text-secondary)] truncate flex-1 min-w-0 font-medium">
                          {item.title}
                        </span>
                        <span className="text-danger-fg text-xs shrink-0 font-semibold tabular-nums">
                          {(item.confidence * 100).toFixed(0)}%
                        </span>
                        <Button
                          onClick={() => handleConfirmConfidence(item.memory_id)}
                          disabled={processing.has(item.memory_id)}
                          variant="ghost"
                          size="xs"
                          className="text-danger-fg hover:bg-warning/10 md:opacity-0 md:group-hover:opacity-100"
                        >
                          {processing.has(item.memory_id) ? t.common.loading : t.home.confirmed}
                        </Button>
                      </motion.div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        {/* ═══ 分区二：到期复习（卡内分区，非独立卡片） ═══ */}
        {hasDueReviews && (
          <div
            className={`flex flex-1 flex-col${hasSuggestions ? ' mt-5 border-t border-[var(--border-default)] pt-4' : ''}`}
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-info/25 to-info/10 shrink-0 ring-1 ring-info/30 border border-info/25 shadow-warm-xs">
                <BookOpen size={15} className="text-info-fg" aria-hidden="true" />
              </div>
              <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">
                {t.home.dueReview}
              </h3>
              <div className="w-1 h-5 bg-gradient-to-b from-info/60 to-info rounded-full ml-1" />
              <Badge className="ml-auto text-sm font-semibold tabular-nums bg-surface-elevated/50 text-[var(--text-secondary)] border border-[var(--border-default)] shadow-warm-xs">
                {translate(t.home.dueCount, { n: reviewStatsQuery.data!.due_now })}
              </Badge>
            </div>
            <p className="text-xs text-[var(--text-secondary)] mb-4 ml-12 font-medium">
              {t.home.dueReviewSubtitle}
            </p>

            <div className="flex flex-1 flex-col justify-center space-y-1.5">
              {dueReviewsQuery.data!.slice(0, 3).map((item, i) => (
                <MotionLink
                  key={item.memory_id}
                  to={`/review?id=${item.memory_id}`}
                  className="relative flex items-center gap-3 px-3 py-2.5 rounded-xl border border-[var(--glass-border)] hover:border-info/40 hover:bg-info/5 transition-all duration-150 group"
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.5 + i * 0.08, duration: duration.stagger }}
                >
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-full bg-info opacity-40 transition-opacity duration-150" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[var(--text-primary)] truncate font-semibold leading-5">
                      {item.title}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <span
                        className={`text-xs px-2 py-0.5 rounded-lg font-semibold ${MASTERY_COLORS[item.mastery_level] ?? 'bg-surface-elevated/50 text-[var(--text-secondary)] border border-[var(--border-default)]'}`}
                      >
                        {t.review[`mastery_${item.mastery_level}` as keyof typeof t.review] ??
                          item.mastery_level}
                      </span>
                      <span className="text-xs text-[var(--text-secondary)] font-medium">
                        {typeLabel(t.common, item.memory_type)}
                      </span>
                      {item.days_overdue > 0 && (
                        <span className="text-xs text-danger-fg font-semibold">
                          {t.review.daysOverdue.replace('{n}', String(item.days_overdue))}
                        </span>
                      )}
                    </div>
                  </div>
                  <ArrowRight
                    size={14}
                    className="text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)] group-hover:translate-x-0.5 transition-all duration-150 shrink-0"
                    aria-hidden="true"
                  />
                </MotionLink>
              ))}
            </div>

            <Link
              to="/review"
              className="group flex items-center justify-center gap-2 mt-4 pt-2.5 border-t border-[var(--border-default)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-surface-inset/30 font-semibold transition-all duration-150 rounded-b-lg -mx-2 px-2"
            >
              {t.home.startReview}
              <ArrowRight
                size={14}
                className="group-hover:translate-x-0.5 transition-all duration-150"
                aria-hidden="true"
              />
            </Link>
          </div>
        )}
      </Card>
    </motion.div>
  )
}
