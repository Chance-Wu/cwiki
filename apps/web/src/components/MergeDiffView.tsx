import { memo, useMemo, useState, useCallback, useEffect, useRef } from 'react'
import { computeAlignedRows, type AlignedDiffRow } from '../lib/diff'
import MarkdownContent from './MarkdownContent'
import { Card } from './ui/Card'
import { useTranslation } from '../i18n/I18nProvider'
import { ChevronRight, ChevronLeft, ChevronsRightLeft, X, Trash2 } from 'lucide-react'

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

// 变更块决策
type BlockDecision = 'pending' | 'left' | 'right' | 'both' | 'discard'

interface ChangeBlock {
  id: number
  rows: AlignedDiffRow[]
  isChanged: boolean
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
  const [manualMode, setManualMode] = useState(false)
  const [focusedBlockId, setFocusedBlockId] = useState<number | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // 目标 vs 源逐行对齐
  const alignedRows = useMemo(
    () => computeAlignedRows(targetContent, sourceContent),
    [targetContent, sourceContent],
  )

  // 将差异行分组为变更块
  const blocks = useMemo(() => {
    const result: ChangeBlock[] = []
    let currentBlock: AlignedDiffRow[] = []
    let blockId = 0

    const isChanged = (row: AlignedDiffRow) =>
      row.left.type !== 'unchanged' || row.right.type !== 'unchanged'

    for (const row of alignedRows) {
      if (isChanged(row)) {
        currentBlock.push(row)
      } else {
        if (currentBlock.length > 0) {
          result.push({ id: blockId++, rows: currentBlock, isChanged: true })
          currentBlock = []
        }
        result.push({ id: blockId++, rows: [row], isChanged: false })
      }
    }
    if (currentBlock.length > 0) {
      result.push({ id: blockId++, rows: currentBlock, isChanged: true })
    }

    return result
  }, [alignedRows])

  // 块决策状态
  const [blockDecisions, setBlockDecisions] = useState<Map<number, BlockDecision>>(() => {
    const map = new Map<number, BlockDecision>()
    for (const block of blocks) {
      map.set(block.id, block.isChanged ? 'pending' : 'left')
    }
    return map
  })

  // 根据决策计算合并内容
  const computedMergedContent = useMemo(() => {
    const lines: string[] = []
    for (const block of blocks) {
      const decision = blockDecisions.get(block.id) ?? 'pending'
      for (const row of block.rows) {
        if (!block.isChanged) {
          lines.push(row.left.content || row.right.content)
        } else {
          switch (decision) {
            case 'left':
              if (row.left.type !== 'empty') lines.push(row.left.content)
              break
            case 'right':
              if (row.right.type !== 'empty') lines.push(row.right.content)
              break
            case 'both':
              if (row.left.type !== 'empty' && row.left.type !== 'unchanged')
                lines.push(row.left.content)
              if (row.right.type !== 'empty' && row.right.type !== 'unchanged')
                lines.push(row.right.content)
              if (row.left.type === 'unchanged' || row.left.type === 'empty')
                if (row.right.type !== 'empty') lines.push(row.right.content)
              break
            case 'discard':
              break
            default:
              if (row.left.type !== 'empty') lines.push(row.left.content)
          }
        }
      }
    }
    return lines.join('\n')
  }, [blocks, blockDecisions])

  // 同步到外部（useEffect 而非 useMemo）
  useEffect(() => {
    if (editable && onMergedChange && !manualMode) {
      onMergedChange(computedMergedContent)
    }
  }, [computedMergedContent, editable, onMergedChange, manualMode])

  // 设置块决策并自动跳转下一个 pending 块
  const setBlockDecision = useCallback(
    (blockId: number, decision: BlockDecision) => {
      setBlockDecisions((prev) => {
        const next = new Map(prev)
        next.set(blockId, decision)
        return next
      })

      // 自动跳转到下一个 pending 块
      const changedBlocks = blocks.filter((b) => b.isChanged)
      const currentIdx = changedBlocks.findIndex((b) => b.id === blockId)
      for (let i = 1; i <= changedBlocks.length; i++) {
        const nextBlock = changedBlocks[(currentIdx + i) % changedBlocks.length]
        const nextDecision = blockDecisions.get(nextBlock.id)
        if (nextDecision === 'pending' && nextBlock.id !== blockId) {
          setFocusedBlockId(nextBlock.id)
          // 滚动到聚焦块
          setTimeout(() => {
            const el = containerRef.current?.querySelector(`[data-block-id="${nextBlock.id}"]`)
            el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
          }, 50)
          break
        }
      }
    },
    [blocks, blockDecisions],
  )

  // 统计
  const stats = useMemo(() => {
    let added = 0,
      removed = 0,
      pending = 0
    for (const block of blocks) {
      const decision = blockDecisions.get(block.id)
      if (decision === 'pending' && block.isChanged) pending++
      for (const row of block.rows) {
        if (row.left.type === 'removed') removed++
        if (row.right.type === 'added') added++
      }
    }
    return { added, removed, pending }
  }, [blocks, blockDecisions])

  // 全部接受左侧/右侧
  const acceptAllLeft = useCallback(() => {
    setBlockDecisions((prev) => {
      const next = new Map(prev)
      for (const block of blocks) {
        if (block.isChanged) next.set(block.id, 'left')
      }
      return next
    })
  }, [blocks])

  const acceptAllRight = useCallback(() => {
    setBlockDecisions((prev) => {
      const next = new Map(prev)
      for (const block of blocks) {
        if (block.isChanged) next.set(block.id, 'right')
      }
      return next
    })
  }, [blocks])

  // 键盘快捷键
  useEffect(() => {
    if (!editable || manualMode) return

    const handleKeyDown = (e: KeyboardEvent) => {
      // 如果焦点在 textarea/input 中，不处理快捷键
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'TEXTAREA' || tag === 'INPUT') return

      if (focusedBlockId === null) return

      switch (e.key) {
        case '1':
          e.preventDefault()
          setBlockDecision(focusedBlockId, 'left')
          break
        case '2':
          e.preventDefault()
          setBlockDecision(focusedBlockId, 'right')
          break
        case '3':
          e.preventDefault()
          setBlockDecision(focusedBlockId, 'both')
          break
        case '4':
          e.preventDefault()
          setBlockDecision(focusedBlockId, 'discard')
          break
        case 'Tab': {
          e.preventDefault()
          const changedBlocks = blocks.filter((b) => b.isChanged)
          const currentIdx = changedBlocks.findIndex((b) => b.id === focusedBlockId)
          const nextIdx = e.shiftKey
            ? (currentIdx - 1 + changedBlocks.length) % changedBlocks.length
            : (currentIdx + 1) % changedBlocks.length
          const nextBlock = changedBlocks[nextIdx]
          setFocusedBlockId(nextBlock.id)
          setTimeout(() => {
            const el = containerRef.current?.querySelector(`[data-block-id="${nextBlock.id}"]`)
            el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
          }, 50)
          break
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [editable, manualMode, focusedBlockId, blocks, setBlockDecision])

  // 初始化聚焦第一个 pending 块
  useEffect(() => {
    if (focusedBlockId === null) {
      const firstPending = blocks.find(
        (b) => b.isChanged && blockDecisions.get(b.id) === 'pending',
      )
      if (firstPending) setFocusedBlockId(firstPending.id)
    }
  }, [blocks, blockDecisions, focusedBlockId])

  return (
    <Card className="overflow-hidden flex flex-col min-h-0 flex-1">
      {/* 顶栏 */}
      <div className="grid grid-cols-[1fr_auto_1fr] border-b border-[var(--glass-border)]">
        <div className="min-w-0 px-3 py-2 bg-surface-inset flex items-center justify-between gap-2 border-r border-[var(--border-default)]">
          <span className="text-xs font-medium text-[var(--text-secondary)] truncate" title={targetFilePath}>
            {targetTitle ?? t.memories.mergeDiffTarget}
          </span>
          <button
            onClick={acceptAllLeft}
            className="shrink-0 px-2 py-0.5 text-xs rounded hover:bg-[var(--surface-card)] transition-colors text-[var(--text-secondary)]"
            title={t.memories.mergeDiffAcceptAllLeft}
          >
            ← {t.common.all ?? 'All'}
          </button>
        </div>
        <div className="px-3 py-2 bg-warning/10 border-r border-warning/20 flex items-center justify-center gap-2">
          <span className="text-xs font-medium text-warning-fg whitespace-nowrap">
            {t.memories.mergeDiffResult}
          </span>
          <div className="flex items-center gap-1.5 text-xs shrink-0">
            {stats.pending > 0 && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-warning/20 text-warning-fg text-xs font-semibold tabular-nums">
                {stats.pending} {t.memories.mergeDiffPendingUnit ?? 'pending'}
              </span>
            )}
            {stats.added > 0 && (
              <span className="text-success-fg tabular-nums">+{stats.added}</span>
            )}
            {stats.removed > 0 && (
              <span className="text-danger-fg tabular-nums">-{stats.removed}</span>
            )}
            {stats.added === 0 && stats.removed === 0 && (
              <span className="text-[var(--text-tertiary)]">{t.memories.mergeDiffNoChanges}</span>
            )}
          </div>
        </div>
        <div className="min-w-0 px-3 py-2 bg-success/10 flex items-center justify-between gap-2">
          <button
            onClick={acceptAllRight}
            className="shrink-0 px-2 py-0.5 text-xs rounded hover:bg-success/20 transition-colors text-success-fg"
            title={t.memories.mergeDiffAcceptAllRight}
          >
            {t.common.all ?? 'All'} →
          </button>
          <span className="text-xs font-medium text-success-fg truncate" title={sourceFilePath}>
            {sourceTitle ?? t.memories.mergeDiffSource}
          </span>
        </div>
      </div>

      {/* 进度条 */}
      {(() => {
        const changedBlocks = blocks.filter(b => b.isChanged)
        const resolved = changedBlocks.filter(b => {
          const d = blockDecisions.get(b.id)
          return d !== 'pending' && d !== undefined
        }).length
        const total = changedBlocks.length
        if (total === 0) return null
        const pct = Math.round((resolved / total) * 100)
        const done = pct === 100
        return (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-surface-inset border-b border-[var(--glass-border)] shrink-0">
            <div className="flex-1 h-1.5 bg-[var(--border-default)] rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-300 ${done ? 'bg-success-fg' : 'bg-primary'}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className={`text-xs tabular-nums shrink-0 ${done ? 'text-success-fg font-medium' : 'text-[var(--text-tertiary)]'}`}>
              {done ? `✓ ${resolved}/${total}` : `${resolved}/${total}`}
            </span>
          </div>
        )
      })()}

      {/* 主体：块级交互 */}
      <div
        ref={containerRef}
        className="overflow-y-auto flex-1 min-h-0"
      >
        {blocks.map((block, idx) => {
          const decision = blockDecisions.get(block.id) ?? 'pending'
          const isFocused = focusedBlockId === block.id
          const prevBlock = idx > 0 ? blocks[idx - 1] : null
          const showSeparator = prevBlock && prevBlock.isChanged && block.isChanged

          return (
            <div key={block.id}>
              {showSeparator && (
                <div className="h-1 bg-[var(--border-default)] opacity-30" />
              )}
              {!block.isChanged ? (
                <ContextBlock rows={block.rows} />
              ) : (
                <ChangeBlockRow
                  block={block}
                  decision={decision}
                  focused={isFocused}
                  onFocus={() => setFocusedBlockId(block.id)}
                  onDecision={(d) => setBlockDecision(block.id, d)}
                  t={t}
                />
              )}
            </div>
          )
        })}
      </div>

      {/* 底部：模式切换 */}
      {editable && (
        <div className="border-t border-[var(--glass-border)] bg-surface-inset shrink-0 flex flex-col min-h-0">
          <div className="px-3 py-2 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setManualMode(false)}
                className={`px-2 py-0.5 rounded-lg text-xs transition-all ${
                  !manualMode
                    ? 'bg-warning/20 text-warning-fg font-medium'
                    : 'text-[var(--text-secondary)] hover:bg-[var(--surface-card)]'
                }`}
              >
                {t.memories.mergeDiffBlockMode}
              </button>
              <button
                onClick={() => setManualMode(true)}
                className={`px-2 py-0.5 rounded-lg text-xs transition-all ${
                  manualMode
                    ? 'bg-warning/20 text-warning-fg font-medium'
                    : 'text-[var(--text-secondary)] hover:bg-[var(--surface-card)]'
                }`}
              >
                {t.memories.mergeDiffManualMode}
              </button>
              {!manualMode && stats.pending === 0 && (
                <span className="text-xs text-success-fg ml-2">✓ {t.memories.mergeSuccess}</span>
              )}
              {!manualMode && focusedBlockId !== null && (
                <div className="hidden md:flex items-center gap-1 ml-3 text-[var(--text-tertiary)]">
                  <kbd className="px-1 py-0.5 bg-surface-card rounded text-[10px] font-mono border border-[var(--border-default)]">1</kbd>
                  <span className="text-[10px]">←</span>
                  <kbd className="px-1 py-0.5 bg-surface-card rounded text-[10px] font-mono border border-[var(--border-default)]">2</kbd>
                  <span className="text-[10px]">→</span>
                  <kbd className="px-1 py-0.5 bg-surface-card rounded text-[10px] font-mono border border-[var(--border-default)]">3</kbd>
                  <span className="text-[10px]">⇔</span>
                  <kbd className="px-1 py-0.5 bg-surface-card rounded text-[10px] font-mono border border-[var(--border-default)]">4</kbd>
                  <Trash2 size={10} className="text-[10px]" />
                  <span className="text-[10px] ml-0.5">Tab ↕</span>
                </div>
              )}
            </div>
            {manualMode && (
              <div className="flex items-center gap-1">
                <button
                  role="tab"
                  aria-selected={mergedTab === 'edit'}
                  onClick={() => setMergedTab('edit')}
                  className={`px-2 py-0.5 rounded-lg text-xs transition-all ${
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
                  onClick={() => setMergedTab('preview')}
                  className={`px-2 py-0.5 rounded-lg text-xs transition-all ${
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
          {manualMode && (
            <div className="border-t border-[var(--glass-border)] flex-1 min-h-0 flex flex-col">
              {mergedTab === 'edit' ? (
                <textarea
                  value={mergedContent}
                  onChange={(e) => onMergedChange!(e.target.value)}
                  className="flex-1 min-h-0 w-full p-2 text-xs font-mono text-[var(--text-secondary)] resize-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-warning bg-transparent"
                  spellCheck={false}
                />
              ) : (
                <div className="flex-1 min-h-0 p-3 overflow-y-auto">
                  <MarkdownContent content={mergedContent!} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

// 未变更上下文块：横跨全宽
const ContextBlock = memo(function ContextBlock({ rows }: { rows: AlignedDiffRow[] }) {
  return (
    <div className="border-b border-[var(--glass-border)] bg-surface-card overflow-x-auto">
      {rows.map((row, idx) => (
        <div key={idx} className="h-5 flex items-center">
          <span className="w-10 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums shrink-0">
            {row.left.lineNum ?? ''}
          </span>
          <span className="px-2 text-xs font-mono text-[var(--text-tertiary)] whitespace-pre leading-5">
            {row.left.content || ' '}
          </span>
        </div>
      ))}
    </div>
  )
})

// 变更块交互行
interface ChangeBlockRowProps {
  block: ChangeBlock
  decision: BlockDecision
  focused: boolean
  onFocus: () => void
  onDecision: (d: BlockDecision) => void
  t: any
}

const ChangeBlockRow = memo(function ChangeBlockRow({
  block,
  decision,
  focused,
  onFocus,
  onDecision,
  t,
}: ChangeBlockRowProps) {
  const decisionBorder: Record<BlockDecision, string> = {
    left: 'border-l-[3px] border-l-primary',
    right: 'border-l-[3px] border-l-success-fg',
    both: 'border-l-[3px] border-l-warning-fg',
    discard: 'border-l-[3px] border-l-danger-fg',
    pending: 'border-l-[3px] border-l-warning/40',
  }

  const decisionBg: Record<BlockDecision, string> = {
    left: 'bg-primary/[0.03]',
    right: 'bg-success/[0.03]',
    both: 'bg-warning/[0.03]',
    discard: 'bg-danger/[0.03] opacity-60',
    pending: '',
  }

  return (
    <div
      data-block-id={block.id}
      onClick={onFocus}
      className={`grid grid-cols-[1fr_auto_1fr] border-b border-[var(--glass-border)] transition-all duration-150 cursor-pointer ${
        decisionBorder[decision]
      } ${decisionBg[decision]} ${focused ? 'ring-1 ring-inset ring-warning/40 bg-warning/[0.03]' : 'hover:bg-[var(--surface-inset)]'}`}
    >
      {/* 左侧：目标内容 */}
      <div className="min-w-0 overflow-x-auto bg-surface-inset border-r border-[var(--border-default)]">
        {block.rows.map((row, idx) => (
          <LeftCell key={idx} row={row} />
        ))}
      </div>

      {/* 中间：操作按钮 */}
      <div className="px-1 py-1 flex flex-col items-center justify-center gap-0.5 bg-surface-inset border-r border-[var(--border-default)]">
        <ActionButton
          active={decision === 'left'}
          activeClass="bg-primary text-white shadow-sm"
          hoverClass="hover:bg-[var(--surface-card)] hover:text-primary"
          onClick={(e) => {
            e.stopPropagation()
            onDecision('left')
          }}
          title={`${t.memories.mergeDiffAcceptLeft} (1)`}
        >
          <ChevronRight size={13} />
        </ActionButton>
        <ActionButton
          active={decision === 'right'}
          activeClass="bg-success-fg text-white shadow-sm"
          hoverClass="hover:bg-success/20 hover:text-success-fg"
          onClick={(e) => {
            e.stopPropagation()
            onDecision('right')
          }}
          title={`${t.memories.mergeDiffAcceptRight} (2)`}
        >
          <ChevronLeft size={13} />
        </ActionButton>
        <ActionButton
          active={decision === 'both'}
          activeClass="bg-warning-fg text-white shadow-sm"
          hoverClass="hover:bg-warning/20 hover:text-warning-fg"
          onClick={(e) => {
            e.stopPropagation()
            onDecision('both')
          }}
          title={`${t.memories.mergeDiffAcceptBoth} (3)`}
        >
          <ChevronsRightLeft size={13} />
        </ActionButton>
        <ActionButton
          active={decision === 'discard'}
          activeClass="bg-danger-fg text-white shadow-sm"
          hoverClass="hover:bg-danger/10 hover:text-danger-fg"
          onClick={(e) => {
            e.stopPropagation()
            onDecision('discard')
          }}
          title={`${t.memories.mergeDiffDiscard} (4)`}
        >
          <X size={13} />
        </ActionButton>
      </div>

      {/* 右侧：来源内容 */}
      <div className="min-w-0 overflow-x-auto bg-success/[0.06]">
        {block.rows.map((row, idx) => (
          <RightCell key={idx} row={row} />
        ))}
      </div>
    </div>
  )
})

// 操作按钮组件
function ActionButton({
  active,
  activeClass,
  hoverClass,
  onClick,
  title,
  children,
}: {
  active: boolean
  activeClass: string
  hoverClass: string
  onClick: (e: React.MouseEvent) => void
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`p-1 rounded transition-all ${active ? activeClass : `text-[var(--text-tertiary)] ${hoverClass}`}`}
    >
      {children}
    </button>
  )
}

const LeftCell = memo(function LeftCell({ row }: { row: AlignedDiffRow }) {
  const { left } = row
  if (left.type === 'empty') {
    return (
      <div className="h-5 bg-surface-card border-b border-[var(--glass-border)]">
        <span className="inline-block w-10 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums" />
      </div>
    )
  }
  const bg = left.type === 'removed' ? 'bg-danger/10' : 'bg-surface-card'
  return (
    <div
      className={`h-5 flex items-center ${bg} border-b border-[var(--glass-border)]`}
    >
      <span className="inline-block w-10 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums shrink-0">
        {left.lineNum ?? ''}
      </span>
      <span className="px-2 text-xs font-mono text-[var(--text-secondary)] whitespace-pre leading-5">
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
        <span className="inline-block w-10 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums" />
      </div>
    )
  }
  const bg = right.type === 'added' ? 'bg-success/10' : 'bg-surface-card'
  return (
    <div
      className={`h-5 flex items-center ${bg} border-b border-[var(--glass-border)]`}
    >
      <span className="inline-block w-10 text-right px-1 text-[var(--text-tertiary)] select-none text-xs leading-5 tabular-nums shrink-0">
        {right.lineNum ?? ''}
      </span>
      <span className="px-2 text-xs font-mono text-[var(--text-secondary)] whitespace-pre leading-5">
        {right.content || ' '}
      </span>
    </div>
  )
})
