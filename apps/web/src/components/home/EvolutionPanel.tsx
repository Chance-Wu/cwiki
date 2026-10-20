import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { duration } from '../../lib/motion'
import { Zap } from 'lucide-react'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { useMemoryStatus } from '../../hooks/useDashboard'
import RingProgress from '../RingProgress'
import { Card } from '../ui/Card'

export default function EvolutionPanel({ workspaceId }: { workspaceId?: string }) {
  const { t } = useTranslation()
  const memoryStatusQuery = useMemoryStatus(workspaceId)
  const memoryStatus = memoryStatusQuery.data ?? null
  const [barsVisible, setBarsVisible] = useState(false)

  useEffect(() => {
    if (memoryStatus) {
      const timer = setTimeout(() => setBarsVisible(true), 400)
      return () => clearTimeout(timer)
    }
  }, [memoryStatus])

  if (!memoryStatus) return null

  // 活动指标全零时标注窗口无活动：数字与条形保留，但不再呈现为有意义的进化信号
  const evolutionIdle =
    (memoryStatus.evolution_metrics?.notes?.created ?? 0) === 0 &&
    (memoryStatus.evolution_metrics?.submissions?.total ?? 0) === 0

  return (
    <Card className="flex flex-col p-5 md:p-6 h-full">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-brand-100 to-brand-50 shrink-0 ring-1 ring-brand-200/35 border border-brand-200/25 shadow-warm-xs">
          <Zap size={15} className="text-brand-fg" aria-hidden="true" />
        </div>
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">
          {t.home.evolutionMetrics}
        </h3>
        <div className="w-1 h-5 bg-gradient-to-b from-brand/60 to-brand rounded-full ml-1" />
      </div>
      <p className="text-xs text-[var(--text-tertiary)] mb-4 ml-11 font-medium">
        {evolutionIdle
          ? t.home.evolutionIdle
          : translate(t.home.daysWindow, {
              n: memoryStatus.evolution_metrics?.period_days ?? 7,
            })}
      </p>
      {/* 三条指标横向排：两条进度 + 右侧环形；窄栏下自动折为纵向堆叠 */}
      <div className="flex flex-1 flex-col gap-5 min-[420px]:flex-row min-[420px]:items-stretch min-[420px]:gap-6">
        <div className="flex flex-1 min-w-0 flex-col justify-center gap-5">
          <motion.div
            className="space-y-2"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.3, duration: duration.medium }}
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
              <span className="text-[var(--text-secondary)] font-medium">
                {t.home.notesFormalized}
              </span>
              <span className="font-semibold text-[var(--text-primary)] tabular-nums ml-auto">
                {memoryStatus.evolution_metrics?.notes?.formalized ?? 0} /{' '}
                {memoryStatus.evolution_metrics?.notes?.created ?? 0}
              </span>
            </div>
            <div className="progress-shimmer w-full h-2.5 bg-surface-inset rounded-full overflow-hidden shadow-inner-subtle border border-[var(--border-default)]">
              <div
                className="h-full bg-gradient-to-r from-brand-500 to-brand-400 rounded-full transition-[width] duration-700 ease-out"
                style={{
                  width: barsVisible
                    ? `${(memoryStatus.evolution_metrics?.notes?.formalization_rate ?? 0) * 100}%`
                    : '0%',
                }}
              />
            </div>
            <p className="text-xs text-[var(--text-tertiary)] font-medium tabular-nums">
              {t.home.formalizationRate}{' '}
              {((memoryStatus.evolution_metrics?.notes?.formalization_rate ?? 0) * 100).toFixed(0)}%
            </p>
          </motion.div>
          <motion.div
            className="space-y-2"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.4, duration: duration.medium }}
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
              <span className="text-[var(--text-secondary)] font-medium">
                {t.home.approvalRate}
              </span>
              <span className="font-semibold text-success-fg tabular-nums ml-auto">
                {memoryStatus.evolution_metrics?.submissions?.approved ?? 0} /{' '}
                {memoryStatus.evolution_metrics?.submissions?.total ?? 0}
              </span>
            </div>
            <div className="progress-shimmer w-full h-2.5 bg-surface-inset rounded-full overflow-hidden shadow-inner-subtle border border-[var(--border-default)]">
              <div
                className="h-full bg-gradient-to-r from-success to-success/75 rounded-full transition-[width] duration-700 ease-out"
                style={{
                  width: barsVisible
                    ? `${(memoryStatus.evolution_metrics?.submissions?.approval_rate ?? 0) * 100}%`
                    : '0%',
                }}
              />
            </div>
            <p className="text-xs text-[var(--text-tertiary)] font-medium tabular-nums">
              {t.home.approvalRate}{' '}
              {((memoryStatus.evolution_metrics?.submissions?.approval_rate ?? 0) * 100).toFixed(0)}
              %
            </p>
          </motion.div>
        </div>

        <motion.div
          className="flex shrink-0 items-center justify-center gap-3 border-t border-[var(--border-default)] pt-5 min-[420px]:flex-col min-[420px]:self-stretch min-[420px]:border-l min-[420px]:border-t-0 min-[420px]:pl-6 min-[420px]:pt-0"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: duration.medium }}
        >
          <RingProgress
            value={memoryStatus.evolution_metrics?.memory_health?.avg_confidence ?? 0}
            size={44}
            strokeWidth={4}
            label={`${((memoryStatus.evolution_metrics?.memory_health?.avg_confidence ?? 0) * 100).toFixed(0)}%`}
          />
          <span className="text-xs text-[var(--text-secondary)] font-medium">
            {t.home.avgQuality}
          </span>
        </motion.div>
      </div>
    </Card>
  )
}
