import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Archive, ChevronRight, Loader2 } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { api } from '../../lib/api'
import type { MergeHistoryItem } from '../../lib/api/types'
import { Card } from '../ui/Card'
import { getSimilarityColor } from '../../lib/utils/similarity'

interface MergeHistoryPanelProps {
  workspaceId: string
}

export default function MergeHistoryPanel({ workspaceId }: MergeHistoryPanelProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set())

  const { data, isLoading, error } = useQuery({
    queryKey: ['merge-history', workspaceId],
    queryFn: () => api.getMergeHistory(workspaceId, 20, 0),
    staleTime: 60_000,
  })

  const toggleExpand = (eventId: string) => {
    const newSet = new Set(expandedItems)
    if (newSet.has(eventId)) {
      newSet.delete(eventId)
    } else {
      newSet.add(eventId)
    }
    setExpandedItems(newSet)
  }

  if (isLoading) {
    return (
      <Card className="p-6">
        <div className="flex items-center justify-center gap-2 text-sm text-[var(--text-secondary)]">
          <Loader2 size={16} className="animate-spin" />
          {t.common.loading}
        </div>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className="p-6">
        <div className="flex items-center justify-between gap-2">
          <div className="text-sm text-danger-fg">{t.memories.mergeHistoryError}</div>
          <button
            onClick={() => queryClient.invalidateQueries({ queryKey: ['merge-history', workspaceId] })}
            className="text-xs text-primary hover:text-primary/80 transition-colors"
          >
            {t.common.refresh}
          </button>
        </div>
      </Card>
    )
  }

  const history = data?.items ?? []

  if (history.length === 0) {
    return (
      <Card className="p-6">
        <div className="flex flex-col items-center justify-center gap-2 text-sm text-[var(--text-tertiary)]">
          <History size={24} className="opacity-50" />
          <div>{t.memories.mergeHistoryEmpty}</div>
        </div>
      </Card>
    )
  }

  return (
    <Card className="overflow-hidden">
      <div className="px-4 py-3 border-b border-[var(--border-default)] bg-surface-inset">
        <div className="flex items-center gap-2">
          <History size={16} className="text-[var(--text-secondary)]" />
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            {t.memories.mergeHistoryTitle}
          </h3>
          <span className="text-xs text-[var(--text-tertiary)]">
            {history.length === 1
              ? t.memories.mergeHistoryCountOne
              : t.memories.mergeHistoryCount.replace('{n}', String(history.length))}
          </span>
        </div>
      </div>
      <div className="divide-y divide-[var(--border-default)]">
        {history.map((item) => (
          <MergeHistoryItem
            key={item.event_id}
            item={item}
            expanded={expandedItems.has(item.event_id)}
            onToggle={() => toggleExpand(item.event_id)}
          />
        ))}
      </div>
    </Card>
  )
}

interface MergeHistoryItemProps {
  item: MergeHistoryItem
  expanded: boolean
  onToggle: () => void
}

function MergeHistoryItem({ item, expanded, onToggle }: MergeHistoryItemProps) {
  const { t } = useTranslation()
  const mergedDate = new Date(item.merged_at)
  const timeAgo = getTimeAgo(mergedDate, t)

  return (
    <div className="group">
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-surface-inset transition-colors text-left"
      >
        <div className="shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
          <Archive size={14} className="text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-sm font-medium text-[var(--text-primary)] truncate">
              {item.keeper_memory.title}
            </span>
            {item.similarity && (
              <span
                className={`text-xs font-semibold tabular-nums ${getSimilarityColor(
                  item.similarity,
                )}`}
              >
                {Math.round(item.similarity * 100)}%
              </span>
            )}
            {item.strategy && (
              <span className="text-xs text-[var(--text-tertiary)] px-1.5 py-0.5 bg-[var(--surface-inset)] rounded">
                {item.strategy}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)]">
            <span>{timeAgo}</span>
            <span>•</span>
            <span>
              {item.archived_memories.length === 1
                ? t.memories.mergeHistoryArchivedOne
                : t.memories.mergeHistoryArchived.replace('{n}', String(item.archived_memories.length))}
            </span>
            {item.event_type === 'auto_merged' && (
              <>
                <span>•</span>
                <span className="text-primary">{t.memories.mergeHistoryAutoMerged}</span>
              </>
            )}
          </div>
        </div>
        <ChevronRight
          size={16}
          className={`shrink-0 text-[var(--text-tertiary)] transition-transform ${
            expanded ? 'rotate-90' : ''
          }`}
        />
      </button>

      {expanded && (
        <div className="px-4 pb-3 pl-15">
          <div className="ml-11 space-y-2">
            <div className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide mb-1">
              {t.memories.mergeHistoryArchivedSection}
            </div>
            {item.archived_memories.map((archived: { id: string; title: string; status: string }) => (
              <div
                key={archived.id}
                className="flex items-center gap-2 text-sm text-[var(--text-secondary)]"
              >
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--text-tertiary)]" />
                <span className="truncate">{archived.title}</span>
                <span className="text-xs text-[var(--text-tertiary)]">({archived.status})</span>
              </div>
            ))}
            <div className="pt-2 text-xs text-[var(--text-tertiary)]">
              {t.memories.mergeHistoryRestoreHint}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function getTimeAgo(date: Date, t: any): string {
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return t.memories.timeAgoJustNow
  if (diffMins < 60) return t.memories.timeAgoMinutes.replace('{n}', String(diffMins))
  if (diffHours < 24) return t.memories.timeAgoHours.replace('{n}', String(diffHours))
  if (diffDays < 7) return t.memories.timeAgoDays.replace('{n}', String(diffDays))
  return date.toLocaleDateString()
}
