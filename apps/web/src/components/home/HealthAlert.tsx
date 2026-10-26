import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight } from 'lucide-react'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { useConsistency, useServiceHealth, useTaskQueueStatus } from '../../hooks/useDashboard'

/** 首页异常告警条：只在任务失败 / 存储不一致 / 服务降级时出现，点击进入设置页监控 */
export default function HealthAlert() {
  const { t } = useTranslation()
  const queueQuery = useTaskQueueStatus()
  const consistencyQuery = useConsistency()
  const healthQuery = useServiceHealth()

  const issues: string[] = []
  const failedTasks = queueQuery.data?.failed.total ?? 0
  if (failedTasks > 0) {
    issues.push(translate(t.home.alertFailedTasks, { n: failedTasks }))
  }
  if (consistencyQuery.data && !consistencyQuery.data.healthy) {
    issues.push(t.home.alertInconsistent)
  }
  if (healthQuery.data && healthQuery.data.status !== 'healthy') {
    issues.push(translate(t.home.alertUnhealthy, { status: healthQuery.data.status }))
  }
  if (issues.length === 0) return null

  return (
    <Link
      to="/settings#monitor"
      className="mb-5 flex items-center gap-2.5 rounded-xl border border-warning/35 bg-warning/10 px-4 py-2.5 no-underline transition-colors hover:border-warning/60 hover:bg-warning/15 md:mb-6"
    >
      <AlertTriangle size={15} className="shrink-0 text-warning-fg" aria-hidden="true" />
      <span className="min-w-0 truncate text-sm font-medium text-[var(--text-primary)]">
        {issues.join(' · ')}
      </span>
      <span className="ml-auto flex shrink-0 items-center gap-1 text-xs font-medium text-warning-fg">
        {t.home.alertView}
        <ArrowRight size={12} aria-hidden="true" />
      </span>
    </Link>
  )
}
