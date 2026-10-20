import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  Database,
  HeartPulse,
  ListTodo,
  Loader2,
  RotateCcw,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import type { TranslationKeys } from '../../i18n/locales/en'
import { useTaskQueueStatus, useConsistency, useServiceHealth } from '../../hooks/useDashboard'
import { api, type TaskQueueStatusResponse } from '../../lib/api'
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
    <span className="inline-flex items-center gap-1.5 text-sm">
      <span
        aria-hidden="true"
        className={`w-2 h-2 rounded-full shrink-0 ${ok ? 'bg-success' : 'bg-danger'}`}
      />
      <span className={ok ? 'text-[var(--text-secondary)]' : 'text-danger-fg font-medium'}>
        {label}
      </span>
    </span>
  )
}

/** 系统诊断卡片：任务队列 / 存储一致性 / 服务健康 三块状态 + 规则式修复建议 + 失败任务重试 */
export default function DiagnosticsPanel() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [retryingTaskId, setRetryingTaskId] = useState<string | null>(null)

  const queueQuery = useTaskQueueStatus()
  const consistencyQuery = useConsistency()
  const healthQuery = useServiceHealth()

  const queue: TaskQueueStatusResponse | null = queueQuery.data ?? null
  const consistency = consistencyQuery.data ?? null
  const health = healthQuery.data ?? null

  const loading = queueQuery.isLoading || consistencyQuery.isLoading || healthQuery.isLoading
  const loadFailed = !loading && !queue && !consistency && !health

  const handleRecheck = () => {
    queueQuery.refetch()
    consistencyQuery.refetch()
    healthQuery.refetch()
  }

  const handleRetryTask = async (taskId: string) => {
    setRetryingTaskId(taskId)
    try {
      await api.retryTaskQueueTask(taskId)
      toast(translate(t.diagnostics.retryQueued, { id: taskId.slice(0, 8) }), 'success')
      // 重试成功后刷新队列快照，失败计数与明细同步减少
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

  // --- 规则式修复建议（零 LLM，纯 if-else 文案）---
  const suggestions: { tone: 'danger' | 'warning' | 'success'; text: string }[] = []
  if (queue && queue.failed.total > 0) {
    suggestions.push({
      tone: 'warning',
      text: translate(t.diagnostics.failedTasksHint, { n: queue.failed.total }),
    })
  }
  const inconsistent = consistency != null && !consistency.healthy
  if (inconsistent) {
    suggestions.push({ tone: 'danger', text: t.diagnostics.inconsistentHint })
  }
  const pendingBacklog =
    queue?.oldest_pending_age_seconds != null && queue.oldest_pending_age_seconds > 300
  if (pendingBacklog) {
    suggestions.push({ tone: 'warning', text: t.diagnostics.backlogHint })
  }
  const allHealthy =
    suggestions.length === 0 && queue != null && consistency != null && health != null
  if (allHealthy) {
    suggestions.push({ tone: 'success', text: t.diagnostics.allHealthy })
  }

  // --- 一致性四方状态：每方独立判定（读取错误或差异数 > 0 即异常）---
  const consistencyRows = consistency
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

  return (
    <Card className="flex flex-col p-5 md:p-6 lg:h-full">
      {/* 标题行 */}
      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-brand-100 to-brand-50 shrink-0 ring-1 ring-brand-200/35 border border-brand-200/25 shadow-warm-xs">
          <Activity size={15} className="text-brand-fg" aria-hidden="true" />
        </div>
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">
          {t.diagnostics.title}
        </h3>
        <div className="w-1 h-5 bg-gradient-to-b from-brand/60 to-brand rounded-full ml-1" />
        <div className="ml-auto">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRecheck}
            disabled={loading || queueQuery.isRefetching || consistencyQuery.isRefetching}
          >
            <Loader2
              size={13}
              className={
                queueQuery.isRefetching || consistencyQuery.isRefetching ? 'animate-spin' : ''
              }
              aria-hidden="true"
            />
            {t.diagnostics.recheck}
          </Button>
        </div>
      </div>

      {loadFailed ? (
        <div className="flex items-center gap-2 text-sm text-[var(--text-tertiary)] py-6 justify-center">
          <AlertTriangle size={15} className="text-warning" aria-hidden="true" />
          {t.diagnostics.loadFailed}
        </div>
      ) : (
        <div className="grid flex-1 grid-cols-1 content-start md:grid-cols-3 gap-5">
          {/* ── 任务队列 ── */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-[var(--text-primary)]">
              <ListTodo size={14} className="text-[var(--text-tertiary)]" aria-hidden="true" />
              {t.diagnostics.queue}
            </div>
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
                  <div className="flex items-center justify-between text-sm pt-1.5 border-t border-[var(--border-default)]">
                    <span className="text-[var(--text-secondary)]">
                      {t.diagnostics.oldestPending}
                    </span>
                    <span
                      className={`font-medium tabular-nums ${
                        pendingBacklog ? 'text-warning-fg' : 'text-[var(--text-primary)]'
                      }`}
                    >
                      {formatAge(queue.oldest_pending_age_seconds, t)}
                    </span>
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-[var(--text-tertiary)]">{t.common.noData}</p>
            )}
          </div>

          {/* ── 存储一致性 ── */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-[var(--text-primary)]">
              <Database size={14} className="text-[var(--text-tertiary)]" aria-hidden="true" />
              {t.diagnostics.consistency}
            </div>
            {consistency ? (
              <div className="space-y-1.5">
                {consistencyRows.map((row) => (
                  <div key={row.key} className="flex items-center justify-between gap-2 text-sm">
                    <StatusDot
                      ok={row.ok}
                      label={row.ok ? row.label : `${row.label} · ${row.detail ?? t.common.error}`}
                    />
                    <span
                      className="text-[var(--text-tertiary)] tabular-nums text-xs"
                      title={row.detail ?? undefined}
                    >
                      {row.count}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--text-tertiary)]">{t.common.noData}</p>
            )}
          </div>

          {/* ── 服务健康 ── */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-[var(--text-primary)]">
              <HeartPulse size={14} className="text-[var(--text-tertiary)]" aria-hidden="true" />
              {t.diagnostics.serviceHealth}
            </div>
            {health ? (
              <div className="space-y-1.5 text-sm">
                <div className="flex items-center justify-between">
                  <StatusDot
                    ok={health.status === 'healthy'}
                    label={
                      health.status === 'healthy'
                        ? t.diagnostics.healthOk
                        : `${t.diagnostics.healthDegraded} · ${health.status}`
                    }
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[var(--text-secondary)]">
                    {t.diagnostics.databaseLabel}
                  </span>
                  <span
                    className={`font-medium text-xs truncate max-w-[140px] ${
                      health.database === 'ok' ? 'text-success-fg' : 'text-danger-fg'
                    }`}
                    title={health.database}
                  >
                    {health.database}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[var(--text-secondary)]">{t.diagnostics.versionLabel}</span>
                  <span className="font-medium text-xs font-mono">{health.version}</span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-[var(--text-tertiary)]">{t.common.noData}</p>
            )}
          </div>
        </div>
      )}

      {/* ── 规则式修复建议 ── */}
      {suggestions.length > 0 && (
        <div className="mt-5 pt-4 border-t border-[var(--border-default)] space-y-2">
          {suggestions.map((s, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              {s.tone === 'success' ? (
                <CheckCircle2
                  size={15}
                  className="text-success shrink-0 mt-0.5"
                  aria-hidden="true"
                />
              ) : (
                <AlertTriangle
                  size={15}
                  className={`shrink-0 mt-0.5 ${s.tone === 'danger' ? 'text-danger-fg' : 'text-warning'}`}
                  aria-hidden="true"
                />
              )}
              <span
                className={
                  s.tone === 'success'
                    ? 'text-success-fg font-medium'
                    : s.tone === 'danger'
                      ? 'text-danger-fg font-medium'
                      : 'text-[var(--text-primary)]'
                }
              >
                {s.text}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── 失败任务明细 + 逐条重试 ── */}
      {queue && queue.failed.items.length > 0 && (
        <div className="mt-auto pt-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              {t.diagnostics.failedTasks}
            </span>
            <span className="text-xs text-[var(--text-tertiary)] tabular-nums">
              {translate(t.diagnostics.failedTaskCount, { n: queue.failed.total })}
            </span>
          </div>
          <div className="space-y-1.5 max-h-48 overflow-y-auto scrollbar-thin pr-1">
            {queue.failed.items.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-inset/40 border border-[var(--border-default)]"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-semibold text-[var(--text-primary)] truncate">
                      {item.name}
                    </span>
                    {item.retry_count > 0 && (
                      <span className="text-2xs text-[var(--text-tertiary)] tabular-nums shrink-0">
                        ×{item.retry_count}
                      </span>
                    )}
                  </div>
                  {item.error && (
                    <p className="text-xs text-[var(--text-tertiary)] truncate" title={item.error}>
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
        </div>
      )}
    </Card>
  )
}
