import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronUp, FolderOpen, Layers } from 'lucide-react'
import { useTranslation, translate } from '../../i18n/I18nProvider'
import { useWorkspacesList } from '../../hooks/useMemories'
import { Card } from '../ui/Card'

const COLLAPSED_ROWS = 5

/** 工作区总览：列出全部工作区与记忆数，点击进入记忆页并按该工作区筛选 */
export default function WorkspaceOverview({ defaultWorkspaceId }: { defaultWorkspaceId?: string }) {
  const { t } = useTranslation()
  const { data, isLoading } = useWorkspacesList()
  const [expanded, setExpanded] = useState(false)

  // 记忆多的排前面，并列时按最近更新时间
  const workspaces = useMemo(
    () =>
      [...(data ?? [])].sort(
        (a, b) =>
          (b.memory_count ?? 0) - (a.memory_count ?? 0) ||
          (b.updated_at ?? '').localeCompare(a.updated_at ?? ''),
      ),
    [data],
  )
  const totalMemories = useMemo(
    () => workspaces.reduce((sum, ws) => sum + (ws.memory_count ?? 0), 0),
    [workspaces],
  )
  const visible = expanded ? workspaces : workspaces.slice(0, COLLAPSED_ROWS)

  return (
    <Card className="p-5 md:p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-info/18 to-info/8 shrink-0 ring-1 ring-info/30">
          <Layers size={15} className="text-info-fg" aria-hidden="true" />
        </div>
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">
          {t.home.workspaceOverview}
        </h3>
        <div className="w-1 h-5 bg-gradient-to-b from-info/60 to-info rounded-full ml-1" />
        {!isLoading && workspaces.length > 0 && (
          <span className="ml-auto text-xs text-[var(--text-tertiary)] tabular-nums">
            {translate(t.home.workspaceSummary, {
              n: workspaces.length,
              m: totalMemories,
            })}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-9 shimmer rounded-lg" />
          ))}
        </div>
      ) : workspaces.length === 0 ? (
        <p className="py-6 text-center text-sm text-[var(--text-tertiary)]">
          {t.home.workspaceEmpty}
        </p>
      ) : (
        <>
          <ul className="space-y-1.5">
            {visible.map((ws) => (
              <li key={ws.id}>
                <Link
                  to={`/memories?workspace=${ws.id}`}
                  className="group flex items-center gap-3 px-3 py-2 rounded-lg border border-[var(--border-default)] bg-surface-inset/40 transition-colors hover:bg-surface-inset/80 hover:border-[var(--border-strong)]"
                >
                  <FolderOpen
                    size={14}
                    className="shrink-0 text-[var(--text-tertiary)] group-hover:text-info-fg"
                    aria-hidden="true"
                  />
                  <span className="min-w-0 truncate text-sm font-medium text-[var(--text-primary)]">
                    {ws.name}
                  </span>
                  {ws.id === defaultWorkspaceId && (
                    <span className="shrink-0 rounded-full bg-info/12 px-2 py-0.5 text-2xs font-medium text-info-fg ring-1 ring-info/25">
                      {t.home.workspaceDefault}
                    </span>
                  )}
                  <span className="ml-auto shrink-0 text-xs tabular-nums text-[var(--text-tertiary)]">
                    {translate(t.home.workspaceMemories, { n: ws.memory_count ?? 0 })}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {workspaces.length > COLLAPSED_ROWS && (
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              className="mt-2 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
            >
              {expanded ? (
                <>
                  <ChevronUp size={13} aria-hidden="true" />
                  {t.common.collapse}
                </>
              ) : (
                <>
                  <ChevronDown size={13} aria-hidden="true" />
                  {translate(t.home.workspaceExpand, { n: workspaces.length - COLLAPSED_ROWS })}
                </>
              )}
            </button>
          )}
        </>
      )}
    </Card>
  )
}
