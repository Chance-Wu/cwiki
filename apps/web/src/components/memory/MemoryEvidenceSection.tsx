import { useState } from 'react'
import { ChevronDown, ChevronRight, Loader2, RotateCcw } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { formatRelativeTime } from '../../lib/format'
import { useMemoryEvidence } from '../../hooks/useMemoryDetail'
import type { MemoryEvidenceItem } from '../../lib/api/memories'

// evidence.source_type 的展示徽标样式：已知值用带色徽标，未知值回退默认灰
const SOURCE_TYPE_STYLES: Record<string, string> = {
  candidate: 'bg-brand-200/40 border-brand-300/35 text-brand-fg',
  episode: 'bg-info/22 border-info/35 text-info-fg',
  event: 'bg-success/22 border-success/35 text-success-fg',
  manual: 'bg-warning/22 border-warning/35 text-warning-fg',
}

interface Props {
  memoryId: string
}

/** 记忆详情 content tab 底部的来源证据区：折叠展示，避免挤压正文阅读区 */
export default function MemoryEvidenceSection({ memoryId }: Props) {
  const { t, locale } = useTranslation()
  const { data, loading, error, reload } = useMemoryEvidence(memoryId)
  const [expanded, setExpanded] = useState(false)

  if (loading) {
    return (
      <div className="mt-4 pt-3 border-t border-dashed border-[var(--border-subtle)] flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
        <Loader2 size={12} className="animate-spin" aria-hidden="true" />
        {t.common.loading}
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-4 pt-3 border-t border-dashed border-[var(--border-subtle)] flex items-center gap-1.5 text-xs text-danger-fg">
        {t.memoryDetail.evidenceLoadFailed}
        <button
          type="button"
          onClick={reload}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md hover:bg-surface-inset transition-colors duration-150"
        >
          <RotateCcw size={11} aria-hidden="true" />
          {t.common.retry}
        </button>
      </div>
    )
  }

  // 无证据时只给一行次要文案，不渲染折叠结构
  if (!data || data.length === 0) {
    return (
      <div className="mt-4 pt-3 border-t border-dashed border-[var(--border-subtle)] text-xs text-[var(--text-tertiary)]">
        {t.memoryDetail.evidenceEmpty}
      </div>
    )
  }

  return (
    <div className="mt-4 pt-3 border-t border-dashed border-[var(--border-subtle)]">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors duration-150 select-none"
      >
        {expanded ? (
          <ChevronDown size={13} aria-hidden="true" />
        ) : (
          <ChevronRight size={13} aria-hidden="true" />
        )}
        {t.memoryDetail.evidenceTitle}
        <span className="tabular-nums text-[var(--text-tertiary)] font-normal">
          {t.memoryDetail.evidenceCount.replace('{n}', String(data.length))}
        </span>
      </button>

      {expanded && (
        <ul className="mt-2.5 space-y-2">
          {data.map((item) => (
            <EvidenceItem key={item.id} item={item} locale={locale} />
          ))}
        </ul>
      )}
    </div>
  )
}

function EvidenceItem({ item, locale }: { item: MemoryEvidenceItem; locale: string }) {
  const { t } = useTranslation()
  const sourceKey = `evidenceSource${item.source_type.charAt(0).toUpperCase()}${item.source_type.slice(1)}`
  // i18n 命名空间下取映射值；未知 source_type 原样展示
  const sourceLabel =
    (t.memoryDetail as Record<string, string>)[sourceKey] ||
    item.source_type ||
    t.memoryDetail.evidenceSourceUnknown

  return (
    <li className="rounded-lg bg-surface-inset border border-[var(--border-default)] shadow-warm-xs px-3 py-2 space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center px-1.5 py-0.5 rounded-md text-2xs font-medium border ${
            SOURCE_TYPE_STYLES[item.source_type] ||
            'bg-surface-elevated/60 border-[var(--glass-border)] text-[var(--text-secondary)]'
          }`}
        >
          {sourceLabel}
        </span>
        <span className="text-2xs text-[var(--text-tertiary)] tabular-nums">
          {formatRelativeTime(item.created_at, t.common, locale)}
        </span>
      </div>
      {item.source_ref && (
        <div
          className="font-mono text-2xs text-[var(--text-secondary)] break-all"
          title={item.source_ref}
        >
          {item.source_ref}
        </div>
      )}
      {item.content && (
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap break-words">
          {item.content}
        </p>
      )}
    </li>
  )
}
