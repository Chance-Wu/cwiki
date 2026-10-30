import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { BarChart3, ClipboardCheck, Folder } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from '../i18n/I18nProvider'
import { api } from '../lib/api'
import { useWorkspacesList } from '../hooks/useMemories'
import { Button } from '../components/ui/Button'
import { Select } from '../components/ui/Select'
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
              clickable ? 'cursor-pointer transition-colors hover:bg-[var(--hover-subtle)]' : ''
            }`}
          >
            <div className="w-24 shrink-0 text-xs text-[var(--text-secondary)]">
              {labels?.[key] || key}
            </div>
            <div className="flex-1 h-6 bg-[var(--surface-inset)] rounded overflow-hidden">
              <motion.div
                className="h-full rounded"
                style={{ backgroundColor: color }}
                initial={{ width: 0 }}
                animate={{ width: `${(value / max) * 100}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
            <div className="w-12 shrink-0 text-right text-sm font-semibold tabular-nums">
              {value}
            </div>
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
    <div className="glass-card p-4 rounded-2xl">
      <div className="text-xs font-medium text-[var(--text-secondary)]">{label}</div>
      <div className="mt-1.5 text-2xl font-bold tabular-nums text-[var(--text-primary)]">
        {value}
      </div>
      {subtext && <div className="text-xs text-[var(--text-tertiary)] mt-1">{subtext}</div>}
    </div>
  )
}

export default function QualityPage() {
  const { t } = useTranslation()
  const [workspaceFilter, setWorkspaceFilter] = useState('all')
  const workspacesQuery = useWorkspacesList()
  const navigate = useNavigate()

  const drill = (params: Record<string, string>) => {
    const q = new URLSearchParams({ status: 'active', ...params })
    // 与质量分布同口径：已选具体工作区时带过去，避免列表口径与分箱数对不上
    if (workspaceFilter !== 'all') q.set('workspace', workspaceFilter)
    navigate(`/memories?${q.toString()}`)
  }
  const drillByRange = (field: 'confidence' | 'importance', key: string) => {
    if (key === 'low') drill({ [`max_${field}`]: '0.4' })
    else if (key === 'medium') drill({ [`min_${field}`]: '0.4', [`max_${field}`]: '0.7' })
    else drill({ [`min_${field}`]: '0.7' })
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['quality-distribution', workspaceFilter],
    queryFn: () =>
      api.getQualityDistribution(workspaceFilter === 'all' ? undefined : workspaceFilter),
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

  const q = t.quality
  const confidenceLabels = { low: q.rangeLow, medium: q.rangeMedium, high: q.rangeHigh }
  const importanceLabels = { low: q.rangeLow, medium: q.rangeMedium, high: q.rangeHigh }
  const usageLabels = {
    unused: q.usageUnused,
    low: q.usageLow,
    medium: q.usageMedium,
    high: q.usageHigh,
  }
  const decayLabels = { fresh: q.decayFresh, aging: q.decayAging, stale: q.decayStale }

  return (
    <PageShell
      maxWidth="max-w-6xl"
      header={
        <motion.div
          className="flex flex-wrap items-center justify-between gap-3"
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <PageTitle icon={<BarChart3 size={18} />} title={q.title} />
          <div className="flex items-center gap-2">
            <Select
              options={[
                { value: 'all', label: t.inbox.workspaceAll },
                ...(workspacesQuery.data ?? []).map((w) => ({
                  value: w.id,
                  label: w.name,
                })),
              ]}
              value={workspaceFilter}
              onChange={setWorkspaceFilter}
              icon={<Folder size={14} />}
            />
            <Button variant="secondary" onClick={() => navigate('/review')}>
              <ClipboardCheck size={14} aria-hidden="true" />
              <span className="hidden sm:inline">{q.reviewCandidates}</span>
            </Button>
          </div>
        </motion.div>
      }
    >
      {isError ? (
        <ErrorAlert message={q.loadFailed} onRetry={() => refetch()} />
      ) : (
        <LoadingWrapper loading={isLoading} skeleton={<CardSkeleton cols={2} />}>
          {data && stats && (
            <div className="space-y-5">
              {/* Summary Stats */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard label={q.total} value={stats.total} />
                <StatCard label={q.avgConfidence} value={stats.avgConfidence} />
                <StatCard label={q.avgImportance} value={stats.avgImportance} />
                <StatCard label={q.avgUsage} value={stats.avgUsage} />
              </div>

              {data.truncated && (
                <div className="rounded-lg border border-[var(--border-default)] bg-[var(--surface-subtle)] px-3 py-2 text-xs text-[var(--text-secondary)]">
                  {q.truncated.replace('{n}', String(data.total))}
                </div>
              )}

              {/* Confidence Distribution */}
              <div className="glass-card rounded-2xl p-5 md:p-6">
                <h3 className="text-base font-semibold mb-4 text-[var(--text-primary)]">
                  {q.confidenceDist}
                </h3>
                <BarChart
                  data={data.confidence_distribution}
                  color="#3b82f6"
                  labels={confidenceLabels}
                  onSelect={(key) => drillByRange('confidence', key)}
                />
              </div>

              {/* Importance Distribution */}
              <div className="glass-card rounded-2xl p-5 md:p-6">
                <h3 className="text-base font-semibold mb-4 text-[var(--text-primary)]">
                  {q.importanceDist}
                </h3>
                <BarChart
                  data={data.importance_distribution}
                  color="#8b5cf6"
                  labels={importanceLabels}
                  onSelect={(key) => drillByRange('importance', key)}
                />
              </div>

              {/* Usage Distribution */}
              <div className="glass-card rounded-2xl p-5 md:p-6">
                <h3 className="text-base font-semibold mb-4 text-[var(--text-primary)]">
                  {q.usageDist}
                </h3>
                <BarChart
                  data={data.usage_distribution}
                  color="#22c55e"
                  labels={usageLabels}
                  onSelect={(key) => drill({ usage: key })}
                />
              </div>

              {/* Decay Distribution */}
              <div className="glass-card rounded-2xl p-5 md:p-6">
                <h3 className="text-base font-semibold mb-4 text-[var(--text-primary)]">
                  {q.decayDist}
                </h3>
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
