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

  return (
    <Card className="p-5 md:p-6 h-full">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-brand-100 to-brand-50 shrink-0 ring-1 ring-brand-200/35 border border-brand-200/25 shadow-warm-xs">
          <Zap size={15} className="text-brand-fg" aria-hidden="true" />
        </div>
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">
          {t.home.evolutionMetrics}
        </h3>
        <div className="w-1 h-5 bg-gradient-to-b from-brand/60 to-brand rounded-full ml-1" />
      </div>
      <p className="text-xs text-[var(--text-tertiary)] mb-3 ml-12 font-medium">
        {translate(t.home.daysWindow, {
          n: memoryStatus.evolution_metrics?.period_days ?? 7,
        })}
      </p>
      <div className="space-y-6">
        <motion.div
          className="space-y-2"
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.3, duration: duration.medium }}
        >
          <div className="flex justify-between text-xs">
            <span className="text-[var(--text-secondary)] font-medium">
              {t.home.notesFormalized}
            </span>
            <span className="font-semibold text-[var(--text-primary)] tabular-nums">
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
          <p className="text-xs text-[var(--text-tertiary)] text-right font-medium tabular-nums">
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
          <div className="flex justify-between text-xs">
            <span className="text-[var(--text-secondary)] font-medium">{t.home.approvalRate}</span>
            <span className="font-semibold text-success-fg tabular-nums">
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
          <p className="text-xs text-[var(--text-tertiary)] text-right font-medium tabular-nums">
            {t.home.approvalRate}{' '}
            {((memoryStatus.evolution_metrics?.submissions?.approval_rate ?? 0) * 100).toFixed(0)}%
          </p>
        </motion.div>
        <motion.div
          className="flex items-center justify-between pt-2.5 border-t border-[var(--border-default)]"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: duration.medium }}
        >
          <span className="text-xs text-[var(--text-secondary)] font-medium">
            {t.home.avgQuality}
          </span>
          <RingProgress
            value={memoryStatus.evolution_metrics?.memory_health?.avg_confidence ?? 0}
            size={36}
            strokeWidth={4}
            label={`${((memoryStatus.evolution_metrics?.memory_health?.avg_confidence ?? 0) * 100).toFixed(0)}%`}
          />
        </motion.div>
      </div>
    </Card>
  )
}
