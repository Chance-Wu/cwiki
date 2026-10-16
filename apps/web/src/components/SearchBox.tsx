import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react'
import { createPortal } from 'react-dom'
import { Search, X, Clock, FileText, Loader2 } from 'lucide-react'
import { useTranslation } from '../i18n/I18nProvider'
import type { FileMemory } from '../lib/api'

export interface SearchBoxHandle {
  focus: () => void
}

interface SearchBoxProps {
  value: string
  onChange: (v: string) => void
  onSubmit: (q: string) => void
  loading?: boolean
  history: string[]
  suggestions: FileMemory[]
  onRemoveHistory: (q: string) => void
  onClearHistory: () => void
}

interface SuggestionItem {
  kind: 'history' | 'memory'
  text: string
}

const SearchBox = forwardRef<SearchBoxHandle, SearchBoxProps>(function SearchBox(
  {
    value,
    onChange,
    onSubmit,
    loading = false,
    history,
    suggestions,
    onRemoveHistory,
    onClearHistory,
  },
  ref,
) {
  const { t } = useTranslation()
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listboxRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 })
  const listboxId = useId()

  const updatePosition = useCallback(() => {
    const inputWrapper = inputRef.current?.parentElement
    if (!inputWrapper) return
    const rect = inputWrapper.getBoundingClientRect()
    setPos({ top: rect.bottom + 6, left: rect.left, width: rect.width })
  }, [])

  useImperativeHandle(ref, () => ({ focus: () => inputRef.current?.focus() }), [])

  const query = value.trim().toLowerCase()

  const items = useMemo<SuggestionItem[]>(() => {
    if (!query) {
      return history.slice(0, 6).map((s) => ({ kind: 'history' as const, text: s }))
    }
    const historyMatches: string[] = []
    for (const h of history) {
      if (historyMatches.length >= 4) break
      if (h.toLowerCase().includes(query)) historyMatches.push(h)
    }
    const memoryMatches: FileMemory[] = []
    for (const m of suggestions) {
      if (memoryMatches.length >= 4) break
      if ((m.title || '').toLowerCase().includes(query)) memoryMatches.push(m)
    }
    const seen = new Set(historyMatches.map((h) => h.toLowerCase()))
    return [
      ...historyMatches.map((text) => ({ kind: 'history' as const, text })),
      ...memoryMatches
        .filter((m) => !seen.has((m.title || '').toLowerCase()))
        .map((m) => ({ kind: 'memory' as const, text: m.title || '' })),
    ]
  }, [query, history, suggestions])

  useEffect(() => {
    setActiveIndex(-1)
  }, [query])

  useEffect(() => {
    if (activeIndex < 0) return
    document.getElementById(`${listboxId}-${activeIndex}`)?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, listboxId])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node
      if (
        rootRef.current &&
        !rootRef.current.contains(target) &&
        listboxRef.current &&
        !listboxRef.current.contains(target)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  useEffect(() => {
    if (!open) return
    updatePosition()
    window.addEventListener('scroll', updatePosition, true)
    window.addEventListener('resize', updatePosition)
    return () => {
      window.removeEventListener('scroll', updatePosition, true)
      window.removeEventListener('resize', updatePosition)
    }
  }, [open, updatePosition])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        e.stopImmediatePropagation()
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  const submit = (q: string) => {
    setOpen(false)
    onSubmit(q)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
        return
      }
      setActiveIndex((i) => {
        if (items.length === 0) return -1
        return e.key === 'ArrowDown' ? Math.min(i + 1, items.length - 1) : Math.max(i - 1, -1)
      })
    } else if (e.key === 'Enter') {
      const item = open ? items[activeIndex] : undefined
      submit(item ? item.text : value)
    } else if (e.key === 'Escape') {
      if (open) {
        setOpen(false)
      } else if (value) {
        onChange('')
      } else {
        inputRef.current?.blur()
      }
    }
  }

  const showPop = open && (query ? true : history.length > 0)

  return (
    <div ref={rootRef} className="flex min-w-0 flex-1 items-center gap-2">
      <div className="relative min-w-0 flex-1">
        <div className="relative flex h-9 items-center rounded-lg border border-[var(--glass-border)] bg-surface-card/80 backdrop-blur-[var(--glass-blur)] shadow-warm-sm transition-[border-color,box-shadow] duration-200 ease-out hover:border-[var(--glass-border-hover)] hover:bg-surface-card hover:shadow-warm-md focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-200/30">
          <Search
            size={14}
            strokeWidth={1.75}
            className="pointer-events-none absolute left-2.5 text-[var(--text-tertiary)]"
            aria-hidden="true"
          />
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded={showPop}
            aria-controls={listboxId}
            aria-activedescendant={activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined}
            aria-autocomplete="list"
            autoComplete="off"
            value={value}
            onChange={(e) => {
              onChange(e.target.value)
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={handleKeyDown}
            placeholder={t.search.placeholder}
            aria-label={t.search.placeholder}
            className="h-full w-full bg-transparent pl-8 pr-9 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
          />
          {value ? (
            <button
              type="button"
              onClick={() => {
                onChange('')
                inputRef.current?.focus()
              }}
              className="absolute right-2.5 rounded p-0.5 text-[var(--text-tertiary)] transition-all duration-150 hover:bg-surface-inset hover:text-[var(--text-secondary)] active:scale-95 select-none"
              aria-label={t.search.clear}
            >
              <X size={13} strokeWidth={1.75} aria-hidden="true" />
            </button>
          ) : (
            !open && (
              <kbd className="pointer-events-none absolute right-2.5 select-none rounded-lg border border-[var(--border-default)] shadow-warm-xs bg-surface-inset px-1.5 py-0.5 font-mono text-3xs text-[var(--text-tertiary)]">
                /
              </kbd>
            )
          )}
        </div>

        {showPop &&
          createPortal(
            <div
              id={listboxId}
              ref={listboxRef}
              role="listbox"
              style={{ position: 'fixed', top: pos.top, left: pos.left, width: pos.width }}
              className="z-dropdown glass-heavy max-h-[280px] origin-top animate-[scale-in_0.1s_ease-out] overflow-y-auto overscroll-contain rounded-lg py-1 scrollbar-thin"
            >
              {!query && (
                <div className="flex items-center justify-between px-3 pb-0.5 pt-1">
                  <span className="text-3xs font-medium uppercase tracking-wider text-[var(--text-tertiary)]">
                    {t.search.recentSearches}
                  </span>
                  <button
                    type="button"
                    aria-label={t.search.clearHistory}
                    onClick={onClearHistory}
                    className="text-xs text-[var(--text-tertiary)] transition-all duration-150 hover:text-[var(--text-secondary)] select-none"
                  >
                    {t.search.clearHistory}
                  </button>
                </div>
              )}
              {items.length > 0 ? (
                items.map((item, i) => (
                  <div
                    key={`${item.kind}-${item.text}`}
                    id={`${listboxId}-${i}`}
                    role="option"
                    aria-selected={i === activeIndex}
                    onClick={() => submit(item.text)}
                    onMouseEnter={() => setActiveIndex(i)}
                    className={`mx-1 flex cursor-pointer select-none items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-all duration-150 ${
                      i === activeIndex ? 'bg-surface-inset' : ''
                    }`}
                  >
                    {item.kind === 'history' ? (
                      <Clock
                        size={12}
                        strokeWidth={1.75}
                        className="shrink-0 text-[var(--text-tertiary)]"
                        aria-hidden="true"
                      />
                    ) : (
                      <FileText
                        size={12}
                        strokeWidth={1.75}
                        className="shrink-0 text-[var(--text-tertiary)]"
                        aria-hidden="true"
                      />
                    )}
                    <span className="min-w-0 flex-1 truncate text-[var(--text-secondary)]">
                      {item.text}
                    </span>
                    {item.kind === 'history' && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          onRemoveHistory(item.text)
                        }}
                        className="shrink-0 rounded p-0.5 text-[var(--text-tertiary)] transition-all duration-150 hover:bg-surface-inset hover:text-[var(--text-secondary)] active:scale-95 select-none"
                        aria-label={`${t.common.delete}: ${item.text}`}
                      >
                        <X size={11} strokeWidth={1.75} aria-hidden="true" />
                      </button>
                    )}
                  </div>
                ))
              ) : query && loading ? (
                <div className="flex items-center gap-2 px-3 py-2.5 text-xs text-[var(--text-tertiary)]">
                  <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                  <span>{t.memories.searching}</span>
                </div>
              ) : query ? (
                <div className="px-3 py-2.5 text-xs text-[var(--text-tertiary)]">
                  {t.search.noResults}
                </div>
              ) : null}
            </div>,
            document.body,
          )}
      </div>

      <button
        type="button"
        onClick={() => submit(value)}
        disabled={loading || !value.trim()}
        className="flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-brand-500 px-3 text-xs font-medium text-[var(--on-brand)] transition-all duration-150 select-none hover:bg-brand-600 active:bg-brand-700 disabled:bg-surface-inset disabled:text-[var(--text-tertiary)] disabled:hover:bg-surface-inset disabled:cursor-not-allowed sm:px-3.5"
        aria-label={t.search.button}
      >
        {loading ? (
          <Loader2 size={13} className="animate-spin" aria-hidden="true" />
        ) : (
          <Search size={13} strokeWidth={1.75} className="sm:hidden" aria-hidden="true" />
        )}
        <span className="hidden sm:inline">{loading ? t.memories.searching : t.search.button}</span>
        <span className="sr-only sm:hidden">
          {loading ? t.memories.searching : t.search.button}
        </span>
      </button>
    </div>
  )
})

export default SearchBox
