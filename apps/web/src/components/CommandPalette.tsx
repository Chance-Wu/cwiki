import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import * as RadixDialog from '@radix-ui/react-dialog'
import { Command, useCommandState } from 'cmdk'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Home,
  Inbox,
  Brain,
  Wrench,
  CheckSquare,
  Settings,
  Sliders,
  Search,
  Moon,
  Sun,
  FileText,
  Loader2,
  type LucideIcon,
} from 'lucide-react'
import { useTranslation, translate, type TranslationKeys } from '../i18n/I18nProvider'
import { duration, spring } from '../lib/motion'
import { api, type FileMemory } from '../lib/api'

interface NavCommand {
  kind: 'nav'
  id: string
  label: string
  icon: LucideIcon
  action: () => void
  group: string
  description: string
}

interface ActionCommand {
  kind: 'action'
  id: string
  label: string
  icon: LucideIcon
  action: () => void
  group: string
}

interface MemoryResult {
  kind: 'memory'
  id: string
  label: string
  icon: LucideIcon
  action: () => void
  group: string
  memory: FileMemory
}

type PaletteItem = NavCommand | ActionCommand | MemoryResult

function formatRelativeTime(dateStr: string, t: TranslationKeys): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diffMs = now - then
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return t.common.justNow
  if (diffMin < 60) return translate(t.common.minutesAgo, { n: diffMin })
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return translate(t.common.hoursAgo, { n: diffHr })
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30) return translate(t.common.daysAgo, { n: diffDay })
  return new Date(dateStr).toLocaleDateString()
}

interface CommandContentProps {
  commands: PaletteItem[]
  memoryItems: PaletteItem[]
  grouped: Map<string, PaletteItem[]>
  searchQuery: string
  searching: boolean
  onSearchChange: (q: string) => void
  t: TranslationKeys
}

function CommandContent({
  commands,
  memoryItems,
  grouped,
  searchQuery,
  searching,
  onSearchChange,
  t,
}: CommandContentProps) {
  const cmdkValue = useCommandState((state) => state.value)

  const typeLabel = useCallback(
    (type: string) => {
      const key = `type${type.charAt(0).toUpperCase()}${type.slice(1)}` as keyof typeof t.common
      return (t.common[key] as string) ?? type
    },
    [t],
  )

  const allItems = useMemo(() => [...commands, ...memoryItems], [commands, memoryItems])

  const selectedItem = useMemo(
    () => allItems.find((item) => item.id === cmdkValue) ?? null,
    [allItems, cmdkValue],
  )

  const previewContent = useMemo(() => {
    if (!selectedItem) return null
    if (selectedItem.kind === 'nav') {
      const Icon = selectedItem.icon
      return {
        type: 'page' as const,
        icon: Icon,
        title: selectedItem.label,
        description: selectedItem.description,
      }
    }
    if (selectedItem.kind === 'memory') {
      const lines = selectedItem.memory.content.split('\n').filter(Boolean).slice(0, 5)
      return {
        type: 'memory' as const,
        title: selectedItem.memory.title,
        memoryType: selectedItem.memory.type,
        updated: selectedItem.memory.updated || selectedItem.memory.created,
        lines,
      }
    }
    return null
  }, [selectedItem])

  return (
    <>
      <div className="flex items-center gap-3 px-5 border-b border-[var(--glass-border)]">
        <Search size={18} className="shrink-0 text-[var(--text-tertiary)]" aria-hidden="true" />
        <Command.Input
          placeholder={t.commandPalette.searchPlaceholder}
          className="flex-1 py-4 text-sm bg-transparent text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none"
          autoFocus
          value={searchQuery}
          onValueChange={onSearchChange}
        />
        {searching && (
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
          >
            <Loader2 size={14} className="animate-spin text-brand-500" />
          </motion.div>
        )}
      </div>

      <div className="flex">
        <div
          className={previewContent ? 'w-[55%] border-r border-[var(--glass-border)]' : 'w-full'}
        >
          <Command.List className="max-h-72 overflow-y-auto scrollbar-thin p-2">
            <Command.Empty className="px-3 py-8 text-center">
              <div className="w-14 h-14 mx-auto mb-2 rounded-xl bg-surface-inset ring-1 ring-brand-border border border-brand-200/25 shadow-warm-xs flex items-center justify-center">
                <Search size={20} className="text-[var(--text-tertiary)]" aria-hidden="true" />
              </div>
              <p className="text-sm text-[var(--text-secondary)]">
                {searchQuery.length >= 2
                  ? t.commandPalette.emptyWithResults
                  : t.commandPalette.emptyNoResults}
              </p>
              {searchQuery.length > 0 && searchQuery.length < 2 && (
                <p className="text-xs text-[var(--text-tertiary)] mt-1">
                  {t.commandPalette.typeMoreHint}
                </p>
              )}
            </Command.Empty>

            {[...grouped.entries()].map(([group, items]) => (
              <Command.Group
                key={group}
                heading={
                  <div className="px-2 py-2 flex items-center gap-2">
                    <span className="text-3xs font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">
                      {group}
                    </span>
                    <div className="flex-1 h-px bg-[var(--border-default)]" />
                  </div>
                }
              >
                <div className="space-y-0.5">
                  {items.map((item) => {
                    const Icon = item.icon
                    return (
                      <Command.Item
                        key={item.id}
                        value={item.id}
                        onSelect={() => item.action()}
                        className="relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs cursor-pointer select-none outline-none text-[var(--text-secondary)] transition-colors duration-150 data-[selected=true]:bg-surface-inset data-[selected=true]:text-[var(--text-primary)]"
                      >
                        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-r-full bg-brand-500 opacity-0 data-[selected=true]:opacity-100 transition-opacity duration-150" />
                        <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-surface-inset border border-[var(--border-default)] shadow-warm-xs text-[var(--text-tertiary)] data-[selected=true]:text-[var(--text-secondary)] transition-colors duration-150 shrink-0">
                          <Icon size={14} strokeWidth={1.75} />
                        </div>
                        <span className="font-medium truncate">{item.label}</span>
                        {item.kind === 'memory' && (
                          <div className="flex items-center gap-2 ml-auto shrink-0">
                            <span className="text-3xs px-1.5 py-0.5 rounded-lg bg-brand-badge-bg text-brand-badge-text font-medium">
                              {typeLabel(item.memory.type)}
                            </span>
                            <span className="text-2xs text-[var(--text-tertiary)]">
                              {formatRelativeTime(item.memory.updated || item.memory.created, t)}
                            </span>
                          </div>
                        )}
                      </Command.Item>
                    )
                  })}
                </div>
              </Command.Group>
            ))}
          </Command.List>
        </div>

        <AnimatePresence mode="wait">
          {previewContent && (
            <motion.div
              key={cmdkValue}
              className="w-[45%] p-4 flex flex-col"
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 8 }}
              transition={{ type: 'spring', ...spring.snappy }}
            >
              {previewContent.type === 'page' && (
                <div className="flex flex-col items-center justify-center h-full text-center gap-3">
                  <div className="w-12 h-12 rounded-xl bg-brand-icon-bg flex items-center justify-center">
                    <previewContent.icon size={22} className="text-brand-500" strokeWidth={1.5} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-[var(--text-primary)]">
                      {previewContent.title}
                    </p>
                    <p className="text-xs text-[var(--text-tertiary)] mt-1 leading-relaxed">
                      {previewContent.description}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 text-2xs text-[var(--text-tertiary)]">
                    <kbd className="inline-flex items-center justify-center px-1.5 h-5 text-3xs font-medium rounded-lg border border-[var(--glass-border)] shadow-warm-xs bg-surface-inset">
                      ↵
                    </kbd>
                    <span>{t.commandPalette.goTo}</span>
                  </div>
                </div>
              )}
              {previewContent.type === 'memory' && (
                <div className="flex flex-col h-full gap-2.5">
                  <div className="flex items-center gap-2">
                    <span className="text-3xs px-1.5 py-0.5 rounded-lg bg-brand-badge-bg text-brand-badge-text font-medium">
                      {typeLabel(previewContent.memoryType)}
                    </span>
                    <span className="text-2xs text-[var(--text-tertiary)]">
                      {formatRelativeTime(previewContent.updated, t)}
                    </span>
                  </div>
                  <p className="text-xs font-semibold text-[var(--text-primary)] leading-snug">
                    {previewContent.title}
                  </p>
                  <div className="flex-1 overflow-hidden">
                    {previewContent.lines.length > 0 ? (
                      <div className="text-xs text-[var(--text-secondary)] leading-relaxed space-y-1">
                        {previewContent.lines.map((line, i) => (
                          <p key={i} className="truncate">
                            {line}
                          </p>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-[var(--text-tertiary)] italic">
                        {t.commandPalette.noPreview}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="flex items-center justify-between px-5 py-2.5 border-t border-[var(--glass-border)] bg-surface-inset/50">
        <div className="flex items-center gap-3 text-2xs text-[var(--text-tertiary)]">
          <span className="flex items-center gap-1">
            <kbd className="inline-flex items-center justify-center w-4 h-4 text-4xs font-medium rounded border border-[var(--glass-border)] bg-surface-inset shadow-warm-xs">
              ⌘
            </kbd>
            <kbd className="inline-flex items-center justify-center w-4 h-4 text-4xs font-medium rounded border border-[var(--glass-border)] bg-surface-inset shadow-warm-xs">
              K
            </kbd>
          </span>
          <span className="flex items-center gap-1">
            <kbd className="inline-flex items-center justify-center w-4 h-4 text-4xs font-medium rounded border border-[var(--glass-border)] bg-surface-inset shadow-warm-xs">
              ↑
            </kbd>
            <kbd className="inline-flex items-center justify-center w-4 h-4 text-4xs font-medium rounded border border-[var(--glass-border)] bg-surface-inset shadow-warm-xs">
              ↓
            </kbd>
            <span className="ml-0.5">{t.commandPalette.navigation}</span>
          </span>
          <span className="flex items-center gap-1">
            <kbd className="inline-flex items-center justify-center px-1 h-4 text-4xs font-medium rounded border border-[var(--glass-border)] bg-surface-inset shadow-warm-xs">
              ↵
            </kbd>
            <span className="ml-0.5">{t.commandPalette.execute}</span>
          </span>
        </div>
        <span className="flex items-center gap-1 text-2xs text-[var(--text-tertiary)]">
          <kbd className="inline-flex items-center justify-center px-1.5 h-4 text-4xs font-medium rounded border border-[var(--glass-border)] bg-surface-inset shadow-warm-xs">
            esc
          </kbd>
          <span className="ml-0.5">{t.common.close}</span>
        </span>
      </div>
    </>
  )
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<FileMemory[]>([])
  const [searching, setSearching] = useState(false)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const navigate = useNavigate()
  const { t, locale, setLocale } = useTranslation()

  const goAndClose = useCallback(
    (path: string) => {
      navigate(path)
      setOpen(false)
    },
    [navigate],
  )

  const pageDescriptions = useMemo<Record<string, string>>(
    () => ({
      '/': t.commandPalette.pageHome,
      '/pending': t.commandPalette.pagePending,
      '/memories': t.commandPalette.pageMemories,
      '/config': t.commandPalette.pageConfig,
      '/skills': t.commandPalette.pageSkills,
      '/review': t.commandPalette.pageReview,
      '/settings': t.commandPalette.pageSettings,
    }),
    [t],
  )

  const isDark =
    typeof document !== 'undefined' && document.documentElement.classList.contains('dark')

  const commands = useMemo<PaletteItem[]>(
    () => [
      {
        kind: 'nav',
        id: 'home',
        label: t.nav.home,
        icon: Home,
        action: () => goAndClose('/'),
        group: t.commandPalette.navigation,
        description: pageDescriptions['/'],
      },
      {
        kind: 'nav',
        id: 'pending',
        label: t.nav.inbox,
        icon: Inbox,
        action: () => goAndClose('/pending'),
        group: t.commandPalette.navigation,
        description: pageDescriptions['/pending'],
      },
      {
        kind: 'nav',
        id: 'memories',
        label: t.nav.memories,
        icon: Brain,
        action: () => goAndClose('/memories'),
        group: t.commandPalette.navigation,
        description: pageDescriptions['/memories'],
      },
      {
        kind: 'nav',
        id: 'skills',
        label: t.nav.skills,
        icon: Wrench,
        action: () => goAndClose('/skills'),
        group: t.commandPalette.navigation,
        description: pageDescriptions['/skills'],
      },
      {
        kind: 'nav',
        id: 'config',
        label: t.nav.config,
        icon: Sliders,
        action: () => goAndClose('/config'),
        group: t.commandPalette.navigation,
        description: pageDescriptions['/config'],
      },
      {
        kind: 'nav',
        id: 'review',
        label: t.nav.review,
        icon: CheckSquare,
        action: () => goAndClose('/review'),
        group: t.commandPalette.navigation,
        description: pageDescriptions['/review'],
      },
      {
        kind: 'nav',
        id: 'settings',
        label: t.nav.settings,
        icon: Settings,
        action: () => goAndClose('/settings'),
        group: t.commandPalette.navigation,
        description: pageDescriptions['/settings'],
      },
      {
        kind: 'action',
        id: 'toggle-theme',
        label: isDark ? t.commandPalette.switchToLight : t.commandPalette.switchToDark,
        icon: isDark ? Sun : Moon,
        action: () => {
          document.documentElement.classList.toggle('dark')
          setOpen(false)
        },
        group: t.commandPalette.actions,
      },
      {
        kind: 'action',
        id: 'toggle-locale',
        label:
          locale === 'zh' ? t.commandPalette.switchToEnglish : t.commandPalette.switchToChinese,
        icon: Search,
        action: () => {
          setLocale(locale === 'zh' ? 'en' : 'zh')
          setOpen(false)
        },
        group: t.commandPalette.actions,
      },
    ],
    [t, locale, setLocale, goAndClose, isDark, pageDescriptions],
  )

  const memoryItems = useMemo<PaletteItem[]>(
    () =>
      searchResults.map((m) => ({
        kind: 'memory' as const,
        id: `mem-${m.id}`,
        label: m.title,
        icon: FileText,
        action: () => {
          goAndClose('/memories')
        },
        group: t.commandPalette.memoriesGroup,
        memory: m,
      })),
    [searchResults, t, goAndClose],
  )

  const allItems = useMemo(() => [...commands, ...memoryItems], [commands, memoryItems])

  const grouped = useMemo(() => {
    const map = new Map<string, PaletteItem[]>()
    for (const item of allItems) {
      const group = item.group
      if (!map.has(group)) map.set(group, [])
      map.get(group)!.push(item)
    }
    return map
  }, [allItems])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    if (!open) {
      setSearchQuery('')
      setSearchResults([])
      return
    }
  }, [open])

  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (searchQuery.length < 2) {
      setSearchResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    searchTimerRef.current = setTimeout(async () => {
      try {
        const res = await api.searchBM25(searchQuery, 5)
        setSearchResults(res.results)
      } catch {
        setSearchResults([])
      } finally {
        setSearching(false)
      }
    }, 300)
    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    }
  }, [searchQuery])

  return (
    <RadixDialog.Root open={open} onOpenChange={setOpen}>
      <AnimatePresence>
        {open && (
          <RadixDialog.Portal forceMount>
            <RadixDialog.Overlay asChild>
              <motion.div
                className="fixed inset-0 z-dialog bg-surface-overlay backdrop-blur-[var(--glass-blur)]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: duration.normal }}
                onClick={() => setOpen(false)}
              />
            </RadixDialog.Overlay>
            <RadixDialog.Content
              className="fixed left-1/2 top-[15%] z-dialog -translate-x-1/2 w-[calc(100%-2rem)] max-w-2xl focus:outline-none"
              forceMount
            >
              <motion.div
                className="glass-heavy rounded-2xl shadow-warm-lg overflow-hidden"
                initial={{ opacity: 0, scale: 0.96, y: -20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.96, y: -20 }}
                transition={{ type: 'spring', ...spring.dialog }}
              >
                <Command
                  className="focus:outline-none"
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                      e.stopPropagation()
                      setOpen(false)
                    }
                  }}
                >
                  <CommandContent
                    commands={commands}
                    memoryItems={memoryItems}
                    grouped={grouped}
                    searchQuery={searchQuery}
                    searching={searching}
                    onSearchChange={setSearchQuery}
                    t={t}
                  />
                </Command>
              </motion.div>
            </RadixDialog.Content>
          </RadixDialog.Portal>
        )}
      </AnimatePresence>
    </RadixDialog.Root>
  )
}
