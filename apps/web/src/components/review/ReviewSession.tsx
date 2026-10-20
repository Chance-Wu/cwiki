import { motion } from 'framer-motion'
import { ArrowUp, Flame, Maximize2, RotateCcw, SkipForward } from 'lucide-react'
import { spring, ease, duration } from '../../lib/motion'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { ReviewCard, QualityButtons } from '../ReviewCard'
import { FocusModeOverlay } from '../FocusModeOverlay'
import { MASTERY_COLORS } from '../../lib/labels'

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

interface ReviewSessionProps {
  currentItem: ReviewItem
  showAnswer: boolean
  setShowAnswer: (v: boolean) => void
  lastResult: {
    mastery_level: string
    interval_days: number
    ease_factor: number
  } | null
  prevMastery: string | null
  sessionStreak: number
  currentIndex: number
  totalItems: number
  progressPct: number
  focusMode: boolean
  setFocusMode: (v: boolean) => void
  handleSkip: () => void
  handleRate: (quality: number) => void
  handleUndo: () => void
  isPending: boolean
  undoPending: boolean
  locale: string
  t: Record<string, unknown>
}

export const ReviewSession = function ReviewSession({
  currentItem,
  showAnswer,
  setShowAnswer,
  lastResult,
  prevMastery,
  sessionStreak,
  currentIndex,
  totalItems,
  progressPct,
  focusMode,
  setFocusMode,
  handleSkip,
  handleRate,
  handleUndo,
  isPending,
  undoPending,
  locale,
  t,
}: ReviewSessionProps) {
  const tr = t.review as Record<string, string>

  return (
    <div>
      {/* 进度条 + 专注模式开关 */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-[var(--text-tertiary)] font-medium">{tr.progress}</span>
          <div className="flex items-center gap-2">
            {sessionStreak >= 2 && (
              <span className="flex items-center gap-1 text-xs text-warning-fg font-medium tabular-nums">
                <Flame size={13} />
                {sessionStreak}
              </span>
            )}
            <span className="text-xs text-[var(--text-tertiary)] tabular-nums font-medium">
              {currentIndex + 1} / {totalItems}
            </span>
            <button
              aria-label={tr.focusMode}
              onClick={() => setFocusMode(!focusMode)}
              className={`p-1 rounded-md transition-all duration-150 ${
                focusMode
                  ? 'bg-info/20 text-info-fg'
                  : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-surface-elevated/40'
              }`}
              title={tr.focusMode}
            >
              <Maximize2 size={14} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className="h-1.5 bg-surface-elevated/30 rounded-full overflow-hidden shadow-inner">
          <motion.div
            className="h-full bg-gradient-to-r from-info/60 to-info rounded-full"
            initial={{ width: 0 }}
            animate={{ width: `${progressPct}%` }}
            transition={{ duration: duration.reveal, ease: ease.out }}
            style={{ boxShadow: '0 0 8px rgb(var(--info-rgb, 59 130 246) / 0.4)' }}
          />
        </div>
      </div>

      {/* 掌握度徽标 */}
      <div className="flex justify-end mb-2 -mt-1">
        <Badge
          className={`font-semibold ${MASTERY_COLORS[currentItem.mastery_level] ?? 'bg-surface-elevated/40 text-[var(--text-secondary)] border border-[var(--border-default)]'}`}
        >
          {tr[`mastery_${currentItem.mastery_level}` as keyof typeof tr] ??
            currentItem.mastery_level}
        </Badge>
      </div>

      {/* 卡片 */}
      <div className={focusMode ? 'relative z-[60]' : ''}>
        <ReviewCard
          item={currentItem}
          showAnswer={showAnswer}
          onShowAnswer={() => setShowAnswer(true)}
          t={t as never}
          locale={locale}
          maxHeight={focusMode ? 'max-h-[55vh]' : undefined}
        />
      </div>

      {/* 跳过按钮 */}
      {!lastResult && (
        <div className="flex justify-center mt-3">
          <Button
            onClick={handleSkip}
            variant="ghost"
            size="sm"
            className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
          >
            <SkipForward size={14} aria-hidden="true" />
            {tr.skip}
            <span className="ml-1.5 text-[10px] opacity-60">S</span>
          </Button>
        </div>
      )}

      {/* 打分结果闪现 + 撤销 */}
      {lastResult && (
        <motion.div
          className="mt-4 space-y-3"
          initial={{ opacity: 0, y: 10, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -10, scale: 0.95 }}
          transition={spring.snappy}
        >
          {/* 掌握度变化 + 下次复习时间 */}
          <div className="flex flex-col items-center gap-2">
            <div className="flex items-center gap-2">
              {prevMastery && prevMastery !== lastResult.mastery_level && (
                <>
                  <Badge className={MASTERY_COLORS[prevMastery] ?? ''}>
                    {tr[`mastery_${prevMastery}` as keyof typeof tr] ?? prevMastery}
                  </Badge>
                  <ArrowUp size={14} className="text-success-fg" />
                </>
              )}
              <Badge
                className={`px-3 py-1 ${MASTERY_COLORS[lastResult.mastery_level] ?? 'bg-surface-elevated/50 text-[var(--text-secondary)] border border-[var(--border-default)]'}`}
              >
                {tr[`mastery_${lastResult.mastery_level}` as keyof typeof tr] ??
                  lastResult.mastery_level}
              </Badge>
              {prevMastery && prevMastery !== lastResult.mastery_level && (
                <span className="text-xs text-success-fg font-medium">{tr.masteryUp}</span>
              )}
            </div>
            <span className="text-xs text-[var(--text-tertiary)]">
              {tr.nextReviewDate.replace(
                '{date}',
                new Date(Date.now() + lastResult.interval_days * 86400000).toLocaleDateString(
                  locale === 'zh' ? 'zh-CN' : 'en-US',
                  { month: 'short', day: 'numeric' },
                ),
              )}
            </span>
          </div>

          {/* 记忆强度条：ease_factor 取值约 1.3（最弱）~ 3.5（最强），线性映射到 0-100% */}
          <div className="flex items-center gap-2 justify-center">
            <span className="text-xs text-[var(--text-tertiary)]">{tr.memoryStrength}</span>
            <div className="w-24 h-1.5 bg-surface-elevated/30 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-danger via-warning to-success rounded-full"
                initial={{ width: 0 }}
                animate={{
                  width: `${Math.min(100, Math.max(0, ((lastResult.ease_factor - 1.3) / 2.2) * 100))}%`,
                }}
                transition={{ duration: duration.reveal, ease: ease.out }}
              />
            </div>
            <span className="text-xs text-[var(--text-tertiary)] tabular-nums">
              {lastResult.ease_factor.toFixed(2)}
            </span>
          </div>

          {/* 撤销按钮 */}
          <div className="flex justify-center">
            <Button
              onClick={handleUndo}
              disabled={undoPending}
              variant="ghost"
              size="sm"
              title={tr.undo}
            >
              <RotateCcw size={14} aria-hidden="true" />
              {tr.undo}
            </Button>
          </div>
        </motion.div>
      )}

      {/* 质量打分按钮 */}
      {!lastResult && showAnswer && (
        <motion.div
          className="mt-5"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={spring.snappy}
        >
          <QualityButtons onRate={handleRate} isPending={isPending} t={t as never} />
        </motion.div>
      )}

      {/* 专注模式全屏遮罩 */}
      {focusMode && (
        <FocusModeOverlay
          item={currentItem}
          showAnswer={showAnswer}
          lastResult={lastResult}
          prevMastery={prevMastery}
          sessionStreak={sessionStreak}
          currentIndex={currentIndex}
          totalItems={totalItems}
          progressPct={progressPct}
          onShowAnswer={() => setShowAnswer(true)}
          onSkip={handleSkip}
          onUndo={handleUndo}
          onRate={handleRate}
          onClose={() => setFocusMode(false)}
          isPending={isPending}
          undoPending={undoPending}
        />
      )}
    </div>
  )
}
