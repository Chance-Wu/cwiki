import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { BarChart3, ClipboardCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useDefaultWorkspace } from '../hooks/useDashboard'
import { Button } from '../components/ui/Button'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import ErrorAlert from '../components/ErrorAlert'
import LoadingWrapper from '../components/LoadingWrapper'
import { CardSkeleton } from '../components/Skeleton'

function BarChart({
  data,
  color,
  labels,
  onSelect,
}: {
  data: Record<string, number>
  color: string
  labels?: Record<string, string>
  onSelect?: (key: string) => void
}) {
  const max = Math.max(...Object.values(data), 1)
  const entries = Object.entries(data)

  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => {
        const clickable = Boolean(onSelect) && value > 0
        return (
          <div
            key={key}
            role={clickable ? 'button' : undefined}
            tabIndex={clickable ? 0 : undefined}
            onClick={clickable ? () => onSelect?.(key) : undefined}
            onKeyDown={
              clickable
                ? (e) => {
                    if (e.key === 'Enter' || e.key === ' ') onSelect?.(key)
                  }
                : undefined
            }
            className={`flex items-center gap-3 rounded px-1 -mx-1 ${
              clickable ? 'cursor-pointer transition-colors hover:bg-[var(--bg-secondary)]' : ''
            }`}
          >
            <div className="w-20 text-sm text-[var(--text-secondary)]">{labels?.[key] || key}</div>
            <div className="flex-1 h-6 bg-[var(--bg-secondary)] rounded overflow-hidden">
              <motion.div
                className="h-full rounded"
                style={{ backgroundColor: color }}
                initial={{ width: 0 }}
                animate={{ width: `${(value / max) * 100}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
            <div className="w-12 text-right text-sm font-semibold">{value}</div>
          </div>
        )
      })}
    </div>
  )
}

function StatCard({
  label,
  value,
  subtext,
}: {
  label: string
  value: string | number
  subtext?: string
}) {
  return (
    <div className="glass-card p-4 rounded-xl">
      <div className="text-sm text-[var(--text-secondary)] mb-1">{label}</div>
      <div className="text-2xl font-bold">{value}</div>
      {subtext && <div className="text-xs text-[var(--text-tertiary)] mt-1">{subtext}</div>}
    </div>
  )
}

export default function QualityPage() {
  const workspaceQuery = useDefaultWorkspace()
  const navigate = useNavigate()

  const drill = (params: Record<string, string>) => {
    const q = new URLSearchParams({ status: 'active', ...params })
    // 与质量分布同口径：限定到默认工作区且只看 active，避免全库计数与分箱数对不上
    if (workspaceQuery.data) q.set('workspace', workspaceQuery.data)
    navigate(`/memories?${q.toString()}`)
  }
  const drillByRange = (field: 'confidence' | 'importance', key: string) => {
    if (key === 'low') drill({ [`max_${field}`]: '0.4' })
    else if (key === 'medium') drill({ [`min_${field}`]: '0.4', [`max_${field}`]: '0.7' })
    else drill({ [`min_${field}`]: '0.7' })
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['quality-distribution', workspaceQuery.data],
    queryFn: () => api.getQualityDistribution(workspaceQuery.data!),
    enabled: !!workspaceQuery.data,
  })

  const stats = useMemo(() => {
    if (!data) return null
    return {
      total: data.total,
      avgConfidence: (data.averages.confidence * 100).toFixed(1) + '%',
      avgImportance: (data.averages.importance * 100).toFixed(1) + '%',
      avgUsage: data.averages.usage_count.toFixed(1),
    }
  }, [data])

  const confidenceLabels = { low: '低 (<0.4)', medium: '中 (0.4-0.7)', high: '高 (≥0.7)' }
  const importanceLabels = { low: '低 (<0.4)', medium: '中 (0.4-0.7)', high: '高 (≥0.7)' }
  const usageLabels = { unused: '未使用', low: '低 (1-4)', medium: '中 (5-19)', high: '高 (≥20)' }
  const decayLabels = { fresh: '新鲜 (<30天)', aging: '老化 (30-90天)', stale: '陈旧 (>90天)' }

  return (
    <PageShell
      maxWidth="max-w-6xl"
      header={
        <motion.div
          className="flex items-center justify-between gap-3"
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <PageTitle
            icon={<BarChart3 size={18} />}
            title="质量分布"
            subtitle="记忆质量与衰减分析 · 点击分箱查看对应记忆"
          />
          <Button variant="secondary" onClick={() => navigate('/review')}>
            <ClipboardCheck size={14} aria-hidden="true" />
            审核待处理候选
          </Button>
        </motion.div>
      }
    >
      {isError ? (
        <ErrorAlert message="加载质量分布失败" onRetry={() => refetch()} />
      ) : (
        <LoadingWrapper loading={isLoading} skeleton={<CardSkeleton cols={2} />}>
          {data && stats && (
            <div className="space-y-6">
              {/* Summary Stats */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard label="总记忆数" value={stats.total} />
                <StatCard label="平均置信度" value={stats.avgConfidence} />
                <StatCard label="平均重要度" value={stats.avgImportance} />
                <StatCard label="平均使用次数" value={stats.avgUsage} />
              </div>

              {data.truncated && (
                <div className="rounded-lg border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-3 py-2 text-xs text-[var(--text-secondary)]">
                  统计截断：单次最多扫描 5000 条，当前仅覆盖 {data.total} 条，结果可能不完整。
                </div>
              )}

              {/* Confidence Distribution */}
              <div className="glass-card rounded-xl p-6">
                <h3 className="text-lg font-semibold mb-4">置信度分布</h3>
                <BarChart
                  data={data.confidence_distribution}
                  color="#3b82f6"
                  labels={confidenceLabels}
                  onSelect={(key) => drillByRange('confidence', key)}
                />
              </div>

              {/* Importance Distribution */}
              <div className="glass-card rounded-xl p-6">
                <h3 className="text-lg font-semibold mb-4">重要度分布</h3>
                <BarChart
                  data={data.importance_distribution}
                  color="#8b5cf6"
                  labels={importanceLabels}
                  onSelect={(key) => drillByRange('importance', key)}
                />
              </div>

              {/* Usage Distribution */}
              <div className="glass-card rounded-xl p-6">
                <h3 className="text-lg font-semibold mb-4">使用频率分布</h3>
                <BarChart
                  data={data.usage_distribution}
                  color="#22c55e"
                  labels={usageLabels}
                  onSelect={(key) => drill({ usage: key })}
                />
              </div>

              {/* Decay Distribution */}
              <div className="glass-card rounded-xl p-6">
                <h3 className="text-lg font-semibold mb-4">衰减分布（基于最后使用时间）</h3>
                <BarChart
                  data={data.decay_distribution}
                  color="#f59e0b"
                  labels={decayLabels}
                  onSelect={(key) => drill({ decay: key })}
                />
              </div>
            </div>
          )}
        </LoadingWrapper>
      )}
    </PageShell>
  )
}
