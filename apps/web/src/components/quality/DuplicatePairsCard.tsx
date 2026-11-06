import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Copy, GitMerge } from 'lucide-react'
import { api } from '../../lib/api'
import { useTranslation } from '../../i18n/I18nProvider'
import ErrorAlert from '../ErrorAlert'

/**
 * 库内重复记忆：active 记忆两两比较的结果，只作合并建议，不自动合并。
 * 扫描规模上限由后端控制（超过 500 条要求按工作区收窄）。
 */
export default function DuplicatePairsCard({ workspaceId }: { workspaceId?: string }) {
  const { t } = useTranslation()
  const q = t.quality
  const queryClient = useQueryClient()
  const merge = useMutation({
    mutationFn: ({ sourceId, targetId }: { sourceId: string; targetId: string }) =>
      api.mergeMemories(sourceId, targetId),
    onSuccess: () => {
      // 合并会改变记忆正文/状态与关系，相关列表一并失效
      queryClient.invalidateQueries({ queryKey: ['memory-duplicates'] })
      queryClient.invalidateQueries({ queryKey: ['memories'] })
      queryClient.invalidateQueries({ queryKey: ['weekly-review'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] })
    },
  })
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['memory-duplicates', workspaceId ?? 'all'],
    queryFn: () => api.getMemoryDuplicates(workspaceId),
    retry: false,
  })

  return (
    <div className="glass-card rounded-2xl p-5 md:p-6">
      <div className="mb-1 flex items-center gap-2">
        <Copy size={15} className="text-[var(--text-tertiary)]" aria-hidden="true" />
        <h3 className="text-base font-semibold text-[var(--text-primary)]">{q.duplicatesTitle}</h3>
      </div>
      <p className="mb-4 text-xs text-[var(--text-tertiary)]">
        {q.duplicatesDesc.replace('{threshold}', String(data?.threshold ?? 0.6))}
      </p>

      {isError ? (
        <ErrorAlert
          message={q.duplicatesFailed}
          onRetry={() => refetch()}
          retryLabel={t.common.retry}
        />
      ) : isLoading ? (
        <p className="text-xs text-[var(--text-tertiary)]">{t.common.loading}</p>
      ) : data && data.pairs.length > 0 ? (
        <ul className="space-y-2">
          {data.pairs.map((pair) => (
            <li
              key={`${pair.left.id}-${pair.right.id}`}
              className="rounded-lg border border-[var(--border-default)] px-3 py-2"
            >
              <div className="flex items-start gap-2 text-xs">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <Link
                    to={`/memories?memoryId=${pair.left.id}`}
                    className="block truncate hover:underline"
                  >
                    {pair.left.title}
                  </Link>
                  <Link
                    to={`/memories?memoryId=${pair.right.id}`}
                    className="block truncate text-[var(--text-secondary)] hover:underline"
                  >
                    {pair.right.title}
                  </Link>
                </div>
                <span className="shrink-0 tabular-nums text-[var(--text-tertiary)]">
                  {(pair.similarity * 100).toFixed(0)}%
                </span>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  disabled={merge.isPending}
                  onClick={() => {
                    const ok = window.confirm(
                      q.duplicatesMergeConfirm
                        .replace('{source}', pair.right.title)
                        .replace('{target}', pair.left.title),
                    )
                    if (ok) merge.mutate({ sourceId: pair.right.id, targetId: pair.left.id })
                  }}
                  className="inline-flex items-center gap-1 rounded border border-[var(--border-default)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)] hover:bg-surface-elevated disabled:opacity-50"
                >
                  <GitMerge size={11} aria-hidden="true" />
                  {q.duplicatesMerge}
                </button>
                {merge.isError && (
                  <span className="text-[11px] text-error-fg">{q.duplicatesMergeFailed}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-[var(--text-tertiary)]">{q.duplicatesEmpty}</p>
      )}

      {data?.truncated && <p className="mt-3 text-xs text-warning-fg">{q.duplicatesTruncated}</p>}
    </div>
  )
}
