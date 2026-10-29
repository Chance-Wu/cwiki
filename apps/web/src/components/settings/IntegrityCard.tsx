import { useQuery } from '@tanstack/react-query'
import { Loader2, RefreshCw, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api } from '../../lib/api'
import { useTranslation } from '../../i18n/I18nProvider'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'

/** 数据一致性巡检卡：展示 DB / MD / _meta / 索引 / 向量 对账结果（只读）。 */
export default function IntegrityCard() {
  const { t } = useTranslation()
  const copy = t.settings

  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ['system-integrity'],
    queryFn: () => api.getSystemIntegrity(),
    staleTime: 30_000,
  })

  const ok = data?.ok === true
  const issues = data?.issues ?? []
  const counts = data?.counts

  return (
    <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)] bg-surface-elevated/20">
      <div className="flex items-center gap-2.5 mb-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-surface-elevated/40 shrink-0 ring-1 ring-subtle">
          {ok ? (
            <ShieldCheck size={15} className="text-success-fg" aria-hidden="true" />
          ) : (
            <ShieldAlert size={15} className="text-warning-fg" aria-hidden="true" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold text-[var(--text-primary)]">
            {copy.integrityTitle}
          </h3>
          <p className="text-xs font-medium text-[var(--text-tertiary)]">{copy.integrityDesc}</p>
        </div>
        <Button
          variant="secondary"
          size="xs"
          onClick={() => refetch()}
          disabled={isFetching}
          title={copy.integrityRefresh}
        >
          {isFetching ? (
            <Loader2 size={13} className="animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw size={13} aria-hidden="true" />
          )}
          {copy.integrityRefresh}
        </Button>
      </div>

      {isLoading ? (
        <p className="text-xs text-[var(--text-tertiary)]">{t.common.loading}</p>
      ) : isError || !data || data.error ? (
        <p className="text-xs text-danger-fg">{copy.integrityUnavailable}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span
              className={ok ? 'font-semibold text-success-fg' : 'font-semibold text-warning-fg'}
            >
              {ok ? copy.integrityOk : copy.integrityIssues.replace('{n}', String(issues.length))}
            </span>
            {counts && (
              <span className="text-[var(--text-tertiary)] tabular-nums">
                DB {counts.db_active}/{counts.db_total} · MD {counts.markdown} · _meta {counts.meta}{' '}
                · 索引 {counts.index} · 向量 {counts.vectors}
              </span>
            )}
          </div>
          {issues.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {issues.map((issue) => (
                <li key={issue.kind} className="text-xs text-[var(--text-secondary)]">
                  <span className="font-semibold text-[var(--text-primary)]">{issue.kind}</span>
                  <span className="tabular-nums"> ×{issue.count}</span>
                  <span className="text-[var(--text-tertiary)]"> · {issue.hint}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-[11px] font-medium text-[var(--text-tertiary)]">
            {copy.integrityFixHint}
          </p>
        </>
      )}
    </Card>
  )
}
