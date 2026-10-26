import { useQuery } from '@tanstack/react-query'
import { BookOpenCheck, Download } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { api } from '../../lib/api'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { Skeleton } from '../Skeleton'

interface Props {
  workspaceId?: string
}

export default function WeeklyReview({ workspaceId }: Props) {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery({
    queryKey: ['weekly-review', workspaceId],
    queryFn: () => api.getWeeklyReview(workspaceId),
    staleTime: 60_000,
  })

  const exportReport = () => {
    if (!data) return
    const lines = [
      `# ${t.weekly.title}`,
      '',
      `${data.period_start} — ${data.period_end}`,
      '',
      `- ${t.weekly.newMemories}: ${data.new_memories}`,
      `- ${t.weekly.reviewed}: ${data.reviewed}`,
      `- ${t.weekly.masteredUp}: ${data.mastered_up}`,
      `- ${t.weekly.pendingNotes}: ${data.pending_notes}`,
      '',
      `## ${t.weekly.mostUsed}`,
      ...(data.most_used.length
        ? data.most_used.map((item) => `- ${item.title} (${item.uses})`)
        : [`- ${t.weekly.noUsage}`]),
      '',
      `## ${t.weekly.actionsTitle}`,
      `- ${t.weekly.conflicts}: ${data.actions.conflicts.length}`,
      ...data.actions.conflicts.map((c) => `  - ${c.description ?? c.id}`),
      `- ${t.weekly.staleMemories}: ${data.actions.stale_memories.length}`,
      ...data.actions.stale_memories.map((m) => `  - ${m.title}`),
      `- ${t.weekly.knowledgeGaps}: ${data.actions.knowledge_gaps.length}`,
      ...data.actions.knowledge_gaps.map((g) => `  - ${g.query} (${g.attempts})`),
      '',
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `cwiki-weekly-${data.period_end}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (!isLoading && !data) return null

  return (
    <Card className="flex flex-col p-4 md:p-5 lg:h-full">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-info/18 to-info/8 ring-1 ring-info/30">
            <BookOpenCheck size={15} className="text-info-fg" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-[var(--text-primary)]">{t.weekly.title}</h3>
            <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
              {data
                ? t.weekly.period
                    .replace('{start}', data.period_start)
                    .replace('{end}', data.period_end)
                : t.weekly.subtitle}
            </p>
          </div>
        </div>
        <Button
          variant="secondary"
          onClick={exportReport}
          disabled={!data || isLoading}
          className="shrink-0"
        >
          <Download size={14} className="mr-1.5" aria-hidden="true" />
          {t.weekly.export}
        </Button>
      </div>

      {isLoading || !data ? (
        <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-xl" />
          ))}
        </div>
      ) : (
        <>
          <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
            {[
              [t.weekly.newMemories, data.new_memories],
              [t.weekly.reviewed, data.reviewed],
              [t.weekly.masteredUp, data.mastered_up],
              [t.weekly.pendingNotes, data.pending_notes],
            ].map(([label, value]) => (
              <div
                key={String(label)}
                className="rounded-xl border border-[var(--border-default)] bg-surface-elevated/20 px-3 py-2"
              >
                <div className="text-lg font-semibold tabular-nums text-[var(--text-primary)]">
                  {value}
                </div>
                <div className="text-2xs text-[var(--text-tertiary)]">{label}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 border-t border-[var(--border-default)] pt-3">
            <div className="mb-1.5 text-xs font-medium text-[var(--text-secondary)]">
              {t.weekly.mostUsed}
            </div>
            {data.most_used.length ? (
              <ol className="space-y-1">
                {data.most_used.map((item, index) => (
                  <li
                    key={item.memory_id}
                    className="flex items-center gap-2 text-xs text-[var(--text-secondary)]"
                  >
                    <span className="w-4 text-right tabular-nums text-[var(--text-tertiary)]">
                      {index + 1}
                    </span>
                    <span className="truncate">{item.title}</span>
                    <span className="ml-auto tabular-nums text-[var(--text-tertiary)]">
                      {item.uses}
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-xs text-[var(--text-tertiary)]">{t.weekly.noUsage}</p>
            )}
          </div>

          <div className="mt-4 border-t border-[var(--border-default)] pt-3">
            <div className="mb-1.5 text-xs font-medium text-[var(--text-secondary)]">
              {t.weekly.actionsTitle}
            </div>
            {data.actions.conflicts.length === 0 &&
            data.actions.stale_memories.length === 0 &&
            data.actions.knowledge_gaps.length === 0 ? (
              <p className="text-xs text-[var(--text-tertiary)]">{t.weekly.noActions}</p>
            ) : (
              <ul className="space-y-1 text-xs text-[var(--text-secondary)]">
                {data.actions.conflicts.map((c) => (
                  <li key={c.id} className="flex items-center gap-2">
                    <span className="rounded bg-warning/15 px-1.5 py-0.5 text-warning-fg">
                      {t.weekly.conflicts}
                    </span>
                    <span className="truncate">{c.description ?? c.id}</span>
                  </li>
                ))}
                {data.actions.stale_memories.map((m) => (
                  <li key={m.memory_id} className="flex items-center gap-2">
                    <span className="rounded bg-danger/15 px-1.5 py-0.5 text-danger-fg">
                      {t.weekly.staleMemories}
                    </span>
                    <span className="truncate">{m.title}</span>
                  </li>
                ))}
                {data.actions.knowledge_gaps.map((g) => (
                  <li key={g.query} className="flex items-center gap-2">
                    <span className="rounded bg-info/15 px-1.5 py-0.5 text-info-fg">
                      {t.weekly.knowledgeGaps}
                    </span>
                    <span className="truncate">{g.query}</span>
                    <span className="ml-auto tabular-nums text-[var(--text-tertiary)]">
                      {g.attempts}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </Card>
  )
}
