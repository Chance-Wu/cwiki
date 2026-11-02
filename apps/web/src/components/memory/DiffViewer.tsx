import { useMemo } from 'react'
import { computeAlignedRows } from '../../lib/diff'

interface DiffViewerProps {
  oldText: string
  newText: string
  oldLabel: string
  newLabel: string
}

/** 只读逐行 diff：左侧旧版本，右侧新版本，增删分别高亮。 */
export default function DiffViewer({ oldText, newText, oldLabel, newLabel }: DiffViewerProps) {
  const rows = useMemo(() => computeAlignedRows(oldText, newText), [oldText, newText])

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border-default)]">
      <div className="grid grid-cols-2 border-b border-[var(--border-default)] bg-surface-inset text-xs font-medium text-[var(--text-secondary)]">
        <div className="truncate border-r border-[var(--border-default)] px-2 py-1.5">
          {oldLabel}
        </div>
        <div className="truncate px-2 py-1.5">{newLabel}</div>
      </div>
      <div className="max-h-[360px] overflow-y-auto font-mono text-xs">
        {rows.map((row, index) => (
          <div key={index} className="grid grid-cols-2">
            <div
              className={`whitespace-pre-wrap break-all border-r border-[var(--border-default)] px-2 py-0.5 ${
                row.left.type === 'removed'
                  ? 'bg-danger/10 text-danger-fg'
                  : row.left.type === 'empty'
                    ? 'bg-surface-inset'
                    : 'text-[var(--text-secondary)]'
              }`}
            >
              {row.left.content || ' '}
            </div>
            <div
              className={`whitespace-pre-wrap break-all px-2 py-0.5 ${
                row.right.type === 'added'
                  ? 'bg-success/10 text-success-fg'
                  : row.right.type === 'empty'
                    ? 'bg-surface-inset'
                    : 'text-[var(--text-secondary)]'
              }`}
            >
              {row.right.content || ' '}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
