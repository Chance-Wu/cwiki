import { motion } from 'framer-motion'
import { X, ArrowUp, Flame, SkipForward, RotateCcw } from 'lucide-react'
import { spring, ease, duration } from '../lib/motion'
import { useTranslation } from '../i18n/I18nProvider'
import { ReviewCard, QualityButtons } from './ReviewCard'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { MASTERY_COLORS } from '../lib/labels'
import type { ReviewItem } from '../lib/api'

interface FocusModeOverlayProps {
  item: ReviewItem
  showAnswer: boolean
  lastResult: { mastery_level: string; interval_days: number; ease_factor: number } | null
  prevMastery: string | null
  sessionStreak: number
  currentIndex: number
  totalItems: number
  progressPct: number
  onShowAnswer: () => void
  onSkip: () => void
  onUndo: () => void
  onRate: (quality: number) => void
  onClose: () => void
  isPending: boolean
  undoPending: boolean
}

export function FocusModeOverlay({
  item,
  showAnswer,
  lastResult,
  prevMastery,
  sessionStreak,
  currentIndex,
  totalItems,
  progressPct,
  onShowAnswer,
  onSkip,
  onUndo,
  onRate,
  onClose,
  isPending,
  undoPending,
}: FocusModeOverlayProps) {
  const { t, locale } = useTranslation()

  return (
    <motion.div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex flex-col items-center justify-center p-6"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: duration.modal }}
    >
      {/* 退出按钮 */}
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors z-10"
        title={t.review.exitFocus}
        aria-label={t.review.exitFocus}
      >
        <X size={20} aria-hidden="true" />
      </button>

      {/* 精简进度条 */}
      <div className="w-full max-w-2xl mb-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-white/50 font-medium">{t.review.progress}</span>
          <div className="flex items-center gap-2">
            {sessionStreak >= 2 && (
              <span className="flex items-center gap-1 text-xs text-warning-fg font-medium tabular-nums">
                <Flame size={13} />
                {sessionStreak}
              </span>
            )}
            <span className="text-xs text-white/50 tabular-nums font-medium">
              {currentIndex + 1} / {totalItems}
            </span>
          </div>
        </div>
        <div className="h-1 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full bg-info/80 rounded-full transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* 专注模式下的卡片 */}
      <div className="w-full max-w-2xl">
        <ReviewCard
          item={item}
          showAnswer={showAnswer}
          onShowAnswer={onShowAnswer}
          t={t}
          locale={locale}
          maxHeight="max-h-[45vh]"
        />

        {/* 跳过按钮 */}
        {!lastResult && (
          <div className="flex justify-center mt-3">
            <Button
              onClick={onSkip}
              variant="ghost"
              size="sm"
              className="text-white/30 hover:text-white/50"
            >
              <SkipForward size={14} aria-hidden="true" />
              {t.review.skip}
              <span className="ml-1.5 text-[10px] opacity-60">S</span>
            </Button>
          </div>
        )}

        {/* 打分结果闪现 */}
        {lastResult && (
          <motion.div
            className="mt-4 flex flex-col items-center gap-2"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={spring.snappy}
          >
            <div className="flex items-center gap-2">
              {prevMastery && prevMastery !== lastResult.mastery_level && (
                <>
                  <Badge className={MASTERY_COLORS[prevMastery] ?? ''}>
                    {t.review[`mastery_${prevMastery}` as keyof typeof t.review] ?? prevMastery}
                  </Badge>
                  <ArrowUp size={14} className="text-success-fg" />
                </>
              )}
              <Badge className={`px-3 py-1 ${MASTERY_COLORS[lastResult.mastery_level] ?? ''}`}>
                {t.review[`mastery_${lastResult.mastery_level}` as keyof typeof t.review] ??
                  lastResult.mastery_level}
              </Badge>
              {prevMastery && prevMastery !== lastResult.mastery_level && (
                <span className="text-xs text-success-fg font-medium">{t.review.masteryUp}</span>
              )}
            </div>
            <span className="text-xs text-white/50">
              {t.review.nextReviewDate.replace(
                '{date}',
                new Date(Date.now() + lastResult.interval_days * 86400000).toLocaleDateString(
                  locale === 'zh' ? 'zh-CN' : 'en-US',
                  { month: 'short', day: 'numeric' },
                ),
              )}
            </span>

            {/* 记忆强度条：ease_factor 约 1.3~3.5，线性映射到 0-100% */}
            <div className="flex items-center gap-2 justify-center">
              <span className="text-xs text-white/40">{t.review.memoryStrength}</span>
              <div className="w-24 h-1.5 bg-white/10 rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-gradient-to-r from-danger via-warning to-success rounded-full"
                  initial={{ width: 0 }}
                  animate={{
                    width: `${Math.min(100, Math.max(0, ((lastResult.ease_factor - 1.3) / 2.2) * 100))}%`,
                  }}
                  transition={{ duration: duration.reveal, ease: ease.out }}
                />
              </div>
              <span className="text-xs text-white/40 tabular-nums">
                {lastResult.ease_factor.toFixed(2)}
              </span>
            </div>

            {/* 撤销按钮 */}
            <Button
              onClick={onUndo}
              disabled={undoPending}
              variant="ghost"
              size="sm"
              className="text-white/40 hover:text-white/60"
              title={t.review.undo}
            >
              <RotateCcw size={14} aria-hidden="true" />
              {t.review.undo}
            </Button>
          </motion.div>
        )}

        {/* 质量打分按钮 */}
        {!lastResult && showAnswer && (
          <motion.div
            className="mt-4"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={spring.snappy}
          >
            <QualityButtons
              onRate={onRate}
              isPending={isPending}
              t={t}
              labelClassName="text-white/60"
              hintClassName="text-white/30"
            />
          </motion.div>
        )}
      </div>

      {/* 键盘快捷键提示 */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-xs text-white/30 font-medium">
        ESC {t.review.exitFocus} · Space {t.review.showAnswer} · S {t.review.skip} · 0-5{' '}
        {t.review.rateQuality}
      </div>
    </motion.div>
  )
}
