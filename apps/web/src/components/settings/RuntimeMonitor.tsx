import { useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Database,
  ListTodo,
  Loader2,
  RefreshCw,
  RotateCcw,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import type { TranslationKeys } from '../../i18n/locales/en'
import { useConsistency, useMetrics, useTaskQueueStatus } from '../../hooks/useDashboard'
import { api } from '../../lib/api'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { useToast } from '../Toast'

/** 秒数 → 人类可读时长（中文界面下显示「N 秒 / N 分钟 / N 小时」） */
function formatAge(seconds: number, t: TranslationKeys): string {
  if (seconds < 60) return translate(t.diagnostics.ageSeconds, { n: Math.floor(seconds) })
  if (seconds < 3600) return translate(t.diagnostics.ageMinutes, { n: Math.floor(seconds / 60) })
  return translate(t.diagnostics.ageHours, { n: Math.floor(seconds / 3600) })
}

/** 状态点：颜色 + 文字双重区分，不完全依赖色彩（符合可访问性偏好） */
function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-sm">
      <span
        aria-hidden="true"
        className={`h-2 w-2 shrink-0 rounded-full ${ok ? 'bg-success' : 'bg-danger'}`}
      />
      <span
        className={`truncate ${ok ? 'text-[var(--text-secondary)]' : 'text-danger-fg font-medium'}`}
      >
        {label}
      </span>
    </span>
  )
}

function CardHeader({
  icon: Icon,
  title,
  action,
}: {
  icon: LucideIcon
  title: string
  action?: ReactNode
}) {
  return (
    <div className="mb-3 flex items-center gap-2.5">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-elevated/40 ring-1 ring-subtle">
        <Icon size={15} className="text-[var(--text-secondary)]" aria-hidden="true" />
      </div>
      <h3 className="text-base font-semibold text-[var(--text-primary)]">{title}</h3>
      {action && <div className="ml-auto">{action}</div>}
    </div>
  )
}

function LoadFailed({ label }: { label: string }) {
  return (
    <div className="flex flex-1 items-center justify-center gap-2 py-6 text-sm text-[var(--text-tertiary)]">
      <AlertTriangle size={15} className="text-warning" aria-hidden="true" />
      {label}
    </div>
  )
}

/** 检索性能：延迟 / 查询量 / 成功率，只依赖 metrics */
function RetrievalCard() {
  const { t } = useTranslation()
  const { data: metrics, isLoading, isFetching, refetch } = useMetrics()

  return (
    <Card className="flex h-full flex-col p-4 md:p-5">
      <CardHeader
        icon={TrendingUp}
        title={t.settings.retrieval}
        action={
          <Button
            variant="ghost"
            size="xs"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label={t.common.refresh}
          >
            <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} aria-hidden="true" />
          </Button>
        }
      />
      {metrics ? (
        <div className="grid grid-cols-2 gap-2">
          {[
            {
              key: 'latency',
              value: (
                <>
                  {metrics.retrieval.avg_latency_ms}
                  <span className="ml-0.5 text-2xs font-normal text-[var(--text-tertiary)]">
                    {t.settings.ms}
                  </span>
                </>
              ),
              label: t.settings.avgLatency,
              tone:
                metrics.retrieval.avg_latency_ms < 100
                  ? 'text-success-fg'
                  : metrics.retrieval.avg_latency_ms < 300
                    ? 'text-warning-fg'
                    : 'text-danger-fg',
            },
            {
              key: 'queries',
              value: metrics.retrieval.queries_24h,
              label: t.settings.queries24h,
              tone: 'text-[var(--text-primary)]',
            },
            {
              key: 'success',
              value: `${(metrics.retrieval.success_rate * 100).toFixed(0)}%`,
              label: t.settings.successRate,
              tone: 'text-success-fg',
            },
            {
              key: 'total',
              value: metrics.retrieval.total_queries,
              label: t.settings.totalQueries,
              tone: 'text-[var(--text-primary)]',
            },
          ].map((item) => (
            <div
              key={item.key}
              className="rounded-lg border border-[var(--border-default)] bg-surface-elevated/20 px-3 py-2"
            >
              <div className={`text-lg font-semibold tabular-nums ${item.tone}`}>{item.value}</div>
              <div className="truncate text-2xs text-[var(--text-tertiary)]">{item.label}</div>
            </div>
          ))}
        </div>
      ) : isLoading ? (
        <div className="flex flex-1 items-center justify-center py-6">
          <Loader2 size={16} className="animate-spin text-[var(--text-tertiary)]" />
        </div>
      ) : (
        <LoadFailed label={t.diagnostics.loadFailed} />
      )}
    </Card>
  )
}

/** 存储一致性：DB / Markdown / 索引 / 向量 四方对账，只依赖 consistency */
function ConsistencyCard() {
  const { t } = useTranslation()
  const { data: consistency, isLoading, isFetching, refetch } = useConsistency()

  const rows = consistency
    ? [
        {
          key: 'db',
          label: t.diagnostics.carrierDb,
          ok: !consistency.errors.db,
          count: consistency.db_count,
          detail: consistency.errors.db ?? null,
        },
        {
          key: 'md',
          label: t.diagnostics.carrierMd,
          ok:
            !consistency.errors.md &&
            consistency.md_missing.length + consistency.md_orphan.length === 0,
          count: consistency.md_count,
          detail:
            consistency.errors.md ??
            (consistency.md_missing.length + consistency.md_orphan.length > 0
              ? `${t.diagnostics.missing} ${consistency.md_missing.length} · ${t.diagnostics.orphan} ${consistency.md_orphan.length}`
              : null),
        },
        {
          key: 'index',
          label: t.diagnostics.carrierIndex,
          ok: !consistency.errors.index && consistency.index_missing.length === 0,
          count: consistency.index_count,
          detail:
            consistency.errors.index ??
            (consistency.index_missing.length > 0
              ? `${t.diagnostics.missing} ${consistency.index_missing.length}`
              : null),
        },
        {
          key: 'vectors',
          label: t.diagnostics.carrierVectors,
          ok: !consistency.errors.vectors && consistency.vectors_missing_total === 0,
          count: consistency.vector_count,
          detail:
            consistency.errors.vectors ??
            (consistency.vectors_missing_total > 0
              ? `${t.diagnostics.missing} ${consistency.vectors_missing_total}`
              : null),
        },
      ]
    : []

  return (
    <Card className="flex h-full flex-col p-4 md:p-5">
      <CardHeader
        icon={Database}
        title={t.diagnostics.consistency}
        action={
          <Button
            variant="ghost"
            size="xs"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label={t.diagnostics.recheck}
          >
            <RotateCcw size={12} className={isFetching ? 'animate-spin' : ''} aria-hidden="true" />
          </Button>
        }
      />
      {consistency ? (
        <div className="space-y-1.5">
          {rows.map((row) => (
            <div key={row.key} className="flex items-center justify-between gap-2 text-sm">
              <StatusDot ok={row.ok} label={row.ok ? row.label : `${row.label} · ${row.detail}`} />
              <span
                className="shrink-0 text-xs tabular-nums text-[var(--text-tertiary)]"
                title={row.detail ?? undefined}
              >
                {row.count}
              </span>
            </div>
          ))}
          {!consistency.healthy && (
            <p className="pt-2 text-xs font-medium text-warning-fg">
              {t.diagnostics.inconsistentHint}
            </p>
          )}
        </div>
      ) : isLoading ? (
        <div className="flex flex-1 items-center justify-center py-6">
          <Loader2 size={16} className="animate-spin text-[var(--text-tertiary)]" />
        </div>
      ) : (
        <LoadFailed label={t.diagnostics.loadFailed} />
      )}
    </Card>
  )
}

/** 任务队列：计数 + 最老待处理 + 失败任务逐条重试，只依赖队列状态 */
function TaskQueueCard() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const { data: queue, isLoading, isFetching, refetch } = useTaskQueueStatus()
  const [retryingTaskId, setRetryingTaskId] = useState<string | null>(null)

  const queueStats = queue
    ? [
        { label: t.diagnostics.queuePending, value: queue.counts.pending, danger: false },
        { label: t.diagnostics.queueRunning, value: queue.counts.running, danger: false },
        { label: t.diagnostics.queueRetrying, value: queue.retry.retrying, danger: false },
        {
          label: t.diagnostics.queueFailed,
          value: queue.counts.failed,
          danger: queue.counts.failed > 0,
        },
      ]
    : []

  const pendingBacklog =
    queue?.oldest_pending_age_seconds != null && queue.oldest_pending_age_seconds > 300

  const handleRetryTask = async (taskId: string) => {
    setRetryingTaskId(taskId)
    try {
      await api.retryTaskQueueTask(taskId)
      toast(translate(t.diagnostics.retryQueued, { id: taskId.slice(0, 8) }), 'success')
      queryClient.invalidateQueries({ queryKey: ['task-queue-status'] })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      // 后端 404 同时覆盖任务不存在与状态非 FAILED 两种情况
      if (message.includes('404') || /not found/i.test(message)) {
        toast(t.diagnostics.retryNotFound, 'warning')
        queryClient.invalidateQueries({ queryKey: ['task-queue-status'] })
      } else {
        toast(t.diagnostics.retryFailedTask, 'error')
      }
    } finally {
      setRetryingTaskId(null)
    }
  }

  return (
    <Card className="flex h-full flex-col p-4 md:p-5">
      <CardHeader
        icon={ListTodo}
        title={t.diagnostics.queue}
        action={
          <Button
            variant="ghost"
            size="xs"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label={t.common.refresh}
          >
            <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} aria-hidden="true" />
          </Button>
        }
      />
      {queue ? (
        <>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {queueStats.map((s) => (
              <div key={s.label} className="flex items-center justify-between text-sm">
                <span className="text-[var(--text-secondary)]">{s.label}</span>
                <span
                  className={`font-semibold tabular-nums ${
                    s.danger ? 'text-danger-fg' : 'text-[var(--text-primary)]'
                  }`}
                >
                  {s.value}
                </span>
              </div>
            ))}
          </div>
          {queue.oldest_pending_age_seconds != null && (
            <div className="mt-1.5 flex items-center justify-between border-t border-[var(--border-default)] pt-1.5 text-sm">
              <span className="text-[var(--text-secondary)]">{t.diagnostics.oldestPending}</span>
              <span
                className={`font-medium tabular-nums ${
                  pendingBacklog ? 'text-warning-fg' : 'text-[var(--text-primary)]'
                }`}
              >
                {formatAge(queue.oldest_pending_age_seconds, t)}
              </span>
            </div>
          )}

          {queue.failed.items.length > 0 && (
            <div className="mt-3 border-t border-[var(--border-default)] pt-2">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-[var(--text-primary)]">
                  {t.diagnostics.failedTasks}
                </span>
                <span className="text-xs tabular-nums text-[var(--text-tertiary)]">
                  {translate(t.diagnostics.failedTaskCount, { n: queue.failed.total })}
                </span>
              </div>
              <div className="max-h-40 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">
                {queue.failed.items.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center gap-2 rounded-lg border border-[var(--border-default)] bg-surface-inset/40 px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-mono text-xs font-semibold text-[var(--text-primary)]">
                          {item.name}
                        </span>
                        {item.retry_count > 0 && (
                          <span className="shrink-0 text-2xs tabular-nums text-[var(--text-tertiary)]">
                            ×{item.retry_count}
                          </span>
                        )}
                      </div>
                      {item.error && (
                        <p
                          className="truncate text-xs text-[var(--text-tertiary)]"
                          title={item.error}
                        >
                          {item.error.length > 120 ? `${item.error.slice(0, 120)}…` : item.error}
                        </p>
                      )}
                    </div>
                    <Button
                      variant="subtle"
                      size="xs"
                      className="shrink-0"
                      disabled={retryingTaskId !== null}
                      onClick={() => handleRetryTask(item.id)}
                    >
                      {retryingTaskId === item.id ? (
                        <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                      ) : (
                        <RotateCcw size={12} aria-hidden="true" />
                      )}
                      {t.common.retry}
                    </Button>
                  </div>
                ))}
              </div>
              {queue.failed.total > queue.failed.items.length && (
                <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
                  {translate(t.settings.failedTasksTruncated, {
                    shown: queue.failed.items.length,
                    total: queue.failed.total,
                  })}
                </p>
              )}
            </div>
          )}
        </>
      ) : isLoading ? (
        <div className="flex flex-1 items-center justify-center py-6">
          <Loader2 size={16} className="animate-spin text-[var(--text-tertiary)]" />
        </div>
      ) : (
        <LoadFailed label={t.diagnostics.loadFailed} />
      )}
    </Card>
  )
}

/** 运行监控：三张独立卡片，任一数据源失败只影响自己那张 */
export default function RuntimeMonitor() {
  return (
    <div className="grid items-start gap-4 lg:grid-cols-3">
      <RetrievalCard />
      <ConsistencyCard />
      <TaskQueueCard />
    </div>
  )
}
