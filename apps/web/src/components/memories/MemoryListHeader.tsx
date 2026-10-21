import { useTranslation } from '../../i18n/I18nProvider'
import { Checkbox } from '../ui/Checkbox'
import { Button } from '../ui/Button'

interface MemoryListHeaderProps {
  countText: string
  visibleCount: number
  selectedCount: number
  onToggleAll: () => void
  showClear: boolean
  onClear: () => void
}

/** 列表区块标题栏：结果计数、键盘快捷键提示（hover 展现）、全选与清除筛选。 */
export default function MemoryListHeader({
  countText,
  visibleCount,
  selectedCount,
  onToggleAll,
  showClear,
  onClear,
}: MemoryListHeaderProps) {
  const { t } = useTranslation()

  return (
    <div className="group flex items-center justify-between mb-3">
      <p className="text-xs text-[var(--text-secondary)] font-medium">{countText}</p>
      <div className="flex items-center gap-3">
        {visibleCount > 0 && (
          <>
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity duration-200">
              <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                /
              </kbd>
              <span className="opacity-70">{t.memories.kbdSearch}</span>
              <span className="opacity-40 mx-0.5">·</span>
              <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                j
              </kbd>
              <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                k
              </kbd>
              <span className="opacity-70">{t.memories.kbdNavigate}</span>
              <span className="opacity-40 mx-0.5">·</span>
              <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                ␣
              </kbd>
              <span className="opacity-70">{t.memories.kbdSelect}</span>
              <span className="opacity-40 mx-0.5">·</span>
              <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                ⏎
              </kbd>
              <span className="opacity-70">{t.memories.kbdOpen}</span>
            </div>
            <div className="flex items-center gap-1.5 text-sm text-[var(--text-secondary)] cursor-pointer select-none hover:text-[var(--text-primary)] transition-all duration-150">
              <Checkbox
                checked={selectedCount === visibleCount && visibleCount > 0}
                onCheckedChange={onToggleAll}
              />
              <span
                role="button"
                tabIndex={0}
                onClick={onToggleAll}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onToggleAll()
                  }
                }}
              >
                {t.memories.selectAll}
              </span>
            </div>
          </>
        )}
        {showClear && (
          <Button onClick={onClear} variant="ghost" size="sm">
            {t.memories.clearSearch}
          </Button>
        )}
      </div>
    </div>
  )
}
