import { memo, useMemo, useState } from 'react'
import { computeAlignedRows, type AlignedDiffRow } from '../lib/diff'
import MarkdownContent from './MarkdownContent'
import { Card } from './ui/Card'
import { useTranslation } from '../i18n/I18nProvider'

interface MergeDiffViewProps {
  targetContent: string
  sourceContent: string
  mergedContent?: string
  onMergedChange?: (value: string) => void
  targetTitle?: string
  sourceTitle?: string
  targetFilePath?: string
  sourceFilePath?: string
}

export default function MergeDiffView({
  targetContent,
  sourceContent,
  mergedContent,
  onMergedChange,
  targetTitle,
  sourceTitle,
  targetFilePath,
  sourceFilePath,
}: MergeDiffViewProps) {
  const { t } = useTranslation()
  const editable = mergedContent !== undefined && onMergedChange !== undefined
  const [mergedTab, setMergedTab] = useState<'edit' | 'preview'>('edit')
  // 目标 vs 源逐行对齐，同时统计净增/净删行数供顶栏展示
  const alignedRows = useMemo(
    () => computeAlignedRows(targetContent, sourceContent),
    [targetContent, sourceContent],
  )

  const stats = useMemo(() => {
    let added = 0,
      removed = 0
    for (const row of alignedRows) {
      if (row.left.type === 'removed') removed++
      if (row.right.type === 'added') added++
    }
    return { added, removed }
  }, [alignedRows])

  return (
    <Card className="overflow-hidden">
      {/* 顶栏：三段与下方三栏对齐 */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr_1.2fr_1fr] border-b border-[var(--glass-border)]">
        <div className="min-w-0 px-3 py-2 bg-surface-inset border-r border-[var(--border-default)]">
          <span className="text-xs font-medium text-[var(--text-secondary)] truncate block">
            {targetFilePath ?? targetTitle ?? 'Target'}
          </span>
        </div>
        <div className="min-w-0 px-3 py-2 bg-warning/10 border-r border-warning/20 flex items-center justify-between">
          <span className="text-xs font-medium text-warning-fg whitespace-nowrap">
            Merged Result
          </span>
          <div className="flex items-center gap-2 text-xs shrink-0">
            {stats.added > 0 && (
              <span className="text-success-fg tabular-nums">+{stats.added}</span>
            )}
            {stats.removed > 0 && (
              <span className="text-danger-fg tabular-nums">-{stats.removed}</span>
            )}
            {stats.added === 0 && stats.removed === 0 && (
              <span className="text-[var(--text-tertiary)]">no changes</span>
            )}
          </div>
        </div>
        <div className="min-w-0 px-3 py-2 bg-success/10">
          <span className="text-xs font-medium text-success-fg truncate block">
            {sourceFilePath ?? sourceTitle ?? 'Source'}
          </span>
        </div>
      </div>

      {/* 三栏布局 */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr_1.2fr_1fr]">
        {/* 左：合并目标 */}
        <div className="min-w-0 overflow-hidden flex flex-col min-h-0 border-r border-[var(--border-default)] bg-surface-inset">
          <div className="px-3 py-1.5 bg-surface-inset border-b border-[var(--glass-border)] text-xs font-medium text-[var(--text-secondary)] truncate">
            {targetFilePath ?? targetTitle ?? 'Target'}
          </div>
          <div
            className="overflow-y-auto flex-1 scrollbar-thin"
            style={{ maxHeight: 'min(420px, 40vh)' }}
          >
            {alignedRows.map((row, idx) => (
              <LeftCell key={idx} row={row} />
            ))}
          </div>
        </div>

        {/* 中：合并结果 */}
        <div className="min-w-0 overflow-hidden flex flex-col min-h-0 border-r border-warning/20 bg-warning/[0.06]">
          <div className="px-3 py-1.5 bg-warning/10 border-b border-warning/20 text-xs font-medium text-warning-fg flex items-center justify-between">
            <span className="whitespace-nowrap">Merged Result</span>
            {editable && (
              <div className="flex items-center gap-1">
                <button
                  role="tab"
                  aria-selected={mergedTab === 'edit'}
                  aria-label={t.merge.source}
                  onClick={() => setMergedTab('edit')}
                  className={`px-2 py-0.5 rounded-lg text-xs transition-all duration-150 select-none active:scale-[0.97] ${
                    mergedTab === 'edit'
                      ? 'bg-warning/20 text-warning-fg'
                      : 'text-warning-fg hover:bg-warning/10'
                  }`}
                >
                  {t.merge.source}
                </button>
                <button
                  role="tab"
                  aria-selected={mergedTab === 'preview'}
                  aria-label={t.merge.preview}
                  onClick={() => setMergedTab('preview')}
                  className={`px-2 py-0.5 rounded-lg text-xs transition-all duration-150 select-none active:scale-[0.97] ${
                    mergedTab === 'preview'
                      ? 'bg-warning/20 text-warning-fg'
                      : 'text-warning-fg hover:bg-warning/10'
                  }`}
                >
                  {t.merge.preview}
                </button>
              </div>
            )}
          </div>
          <div className="flex-1 min-h-0">
            {editable ? (
              mergedTab === 'edit' ? (
                <textarea
                  value={mergedContent}
                  onChange={(e) => onMergedChange!(e.target.value)}
                  className="w-full h-full p-2 text-xs font-mono text-[var(--text-secondary)] resize-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-warning bg-transparent"
                  style={{ minHeight: 'min(420px, 40vh)' }}
                  spellCheck={false}
                />
              ) : (
                <div
                  className="p-3 overflow-y-auto h-full scrollbar-thin"
                  style={{ minHeight: 'min(420px, 40vh)', maxHeight: 'min(420px, 40vh)' }}
                >
                  <MarkdownContent content={mergedContent!} />
                </div>
              )
            ) : (
              <div
                className="p-2 text-xs font-mono text-[var(--text-secondary)] overflow-y-auto scrollbar-thin"
                style={{ minHeight: 'min(420px, 40vh)' }}
              >
                {targetContent}
              </div>
            )}
          </div>
        </div>

        {/* 右：新候选来源 */}
        <div className="min-w-0 overflow-hidden flex flex-col min-h-0 bg-success/[0.06]">
          <div className="px-3 py-1.5 bg-success/10 border-b border-success/20 text-xs font-medium text-success-fg truncate">
            {sourceFilePath ?? sourceTitle ?? 'Source'}
          </div>
          <div
            className="overflow-y-auto flex-1 scrollbar-thin"
            style={{ maxHeight: 'min(420px, 40vh)' }}
          >
            {alignedRows.map((row, idx) => (
              <RightCell key={idx} row={row} />
            ))}
          </div>
        </div>
      </div>
    </Card>
  )
}

const LeftCell = memo(function LeftCell({ row }: { row: AlignedDiffRow }) {
  const { left } = row
  if (left.type === 'empty') {
    return (
      <div className="h-5 bg-surface-card border-b border-[var(--glass-border)]">
        <span className="inline-block w-8 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums" />
      </div>
    )
  }
  const bg = left.type === 'removed' ? 'bg-danger/10' : 'bg-surface-card'
  return (
    <div
      className={`h-5 flex items-center overflow-hidden ${bg} border-b border-[var(--glass-border)]`}
    >
      <span className="inline-block w-8 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums shrink-0">
        {left.lineNum ?? ''}
      </span>
      <span className="px-2 text-xs font-mono text-[var(--text-secondary)] whitespace-pre truncate leading-5 min-w-0">
        {left.content || ' '}
      </span>
    </div>
  )
})

const RightCell = memo(function RightCell({ row }: { row: AlignedDiffRow }) {
  const { right } = row
  if (right.type === 'empty') {
    return (
      <div className="h-5 bg-surface-card border-b border-[var(--glass-border)]">
        <span className="inline-block w-8 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums" />
      </div>
    )
  }
  const bg = right.type === 'added' ? 'bg-success/10' : 'bg-surface-card'
  return (
    <div
      className={`h-5 flex items-center overflow-hidden ${bg} border-b border-[var(--glass-border)]`}
    >
      <span className="inline-block w-8 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums shrink-0">
        {right.lineNum ?? ''}
      </span>
      <span className="px-2 text-xs font-mono text-[var(--text-secondary)] whitespace-pre truncate leading-5 min-w-0">
        {right.content || ' '}
      </span>
    </div>
  )
})
