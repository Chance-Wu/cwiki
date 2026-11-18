import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BookOpen, Check, Loader2, RotateCcw, Save, Sliders } from 'lucide-react'
import { translate, useTranslation } from '../i18n/I18nProvider'
import { spring } from '../lib/motion'
import { CardSkeleton } from '../components/Skeleton'
import ErrorAlert from '../components/ErrorAlert'
import { useToast } from '../components/Toast'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import SectionGroup from '../components/SectionGroup'
import { Button } from '../components/ui/Button'
import WriteDecisionCard from '../components/config/WriteDecisionCard'
import WritePolicyCard from '../components/config/WritePolicyCard'
import { ConfigCard } from '../components/config/ConfigCard'
import { GlossaryDialog, WorkflowCard } from '../components/config/ConfigGlossary'
import {
  ALL_SEARCHABLE_FIELDS,
  advancedFields,
  advancedTheme,
  EDITABLE_SECTIONS,
  featureFlagsTheme,
  featureFlagFields,
  fieldMatches,
  formatPatchError,
  memoryFields,
  memoryTheme,
  mcpFields,
  mcpTheme,
  NAV_ITEMS,
  NUMERIC_FIELDS,
  performanceFields,
  performanceTheme,
  retrievalFields,
  retrievalTheme,
  schedulerFields,
  schedulerTheme,
} from '../components/config/configSchema'
import type { ConfigSection } from '../components/config/configSchema'
import { useConfig } from '../hooks/useSettings'
import { useBeforeUnloadGuard } from '../hooks/useBeforeUnload'
import type { ConfigData } from '../lib/api'

export default function ConfigPage() {
  const { t } = useTranslation()
  const copy = t.config as Record<string, string>
  const { toast } = useToast()
  const { data: config, isLoading, error, refetch, patchConfig } = useConfig()

  const [localConfig, setLocalConfig] = useState<ConfigData | null>(null)
  const [baseline, setBaseline] = useState<ConfigData | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [glossaryOpen, setGlossaryOpen] = useState(false)
  const [fieldSearch, setFieldSearch] = useState('')
  const [activeSection, setActiveSection] = useState(NAV_ITEMS[0].id)

  const matchCount = useMemo(
    () =>
      fieldSearch.trim()
        ? ALL_SEARCHABLE_FIELDS.filter((field) => fieldMatches(field, fieldSearch, copy)).length
        : 0,
    [fieldSearch, copy],
  )
  const savedTimer = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (savedTimer.current) window.clearTimeout(savedTimer.current)
    },
    [],
  )

  useEffect(() => {
    if (config && !localConfig) {
      setLocalConfig(structuredClone(config))
      setBaseline(structuredClone(config))
    }
  }, [config, localConfig])

  const ready = Boolean(localConfig)

  useEffect(() => {
    if (!ready) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (visible?.target.id) setActiveSection(visible.target.id)
      },
      { rootMargin: '-20% 0px -65% 0px', threshold: [0, 0.2, 0.6] },
    )
    NAV_ITEMS.forEach(({ id }) => {
      const element = document.getElementById(id)
      if (element) observer.observe(element)
    })
    return () => observer.disconnect()
  }, [ready])

  const dirtyCount = useMemo(() => {
    if (!baseline || !localConfig) return 0
    const base = baseline as unknown as Record<string, Record<string, unknown>>
    const draft = localConfig as unknown as Record<string, Record<string, unknown>>
    let count = 0
    for (const section of EDITABLE_SECTIONS) {
      const baseSection = base[section] ?? {}
      const draftSection = draft[section] ?? {}
      for (const key of new Set([...Object.keys(baseSection), ...Object.keys(draftSection)])) {
        if (baseSection[key] !== draftSection[key]) count += 1
      }
    }
    return count
  }, [baseline, localConfig])

  const dirtyByNav = useMemo(() => {
    const result: Record<string, number> = {}
    if (!baseline || !localConfig) return result
    const base = baseline as unknown as Record<string, Record<string, unknown>>
    const draft = localConfig as unknown as Record<string, Record<string, unknown>>
    const groupOf = (section: ConfigSection) =>
      section === 'app' || section === 'parasitic_evolution'
        ? 'features'
        : section === 'memory'
          ? 'thresholds'
          : 'performance'
    for (const section of EDITABLE_SECTIONS) {
      const baseSection = base[section] ?? {}
      const draftSection = draft[section] ?? {}
      for (const key of new Set([...Object.keys(baseSection), ...Object.keys(draftSection)])) {
        if (baseSection[key] !== draftSection[key]) {
          const group = groupOf(section)
          result[group] = (result[group] ?? 0) + 1
        }
      }
    }
    return result
  }, [baseline, localConfig])

  const invalidCount = useMemo(() => {
    if (!localConfig) return 0
    const draft = localConfig as unknown as Record<string, Record<string, unknown>>
    let count = 0
    for (const field of NUMERIC_FIELDS) {
      const value = draft[field.section]?.[field.key]
      if (typeof value !== 'number') continue
      if (field.min !== undefined && value < field.min) count += 1
      else if (field.max !== undefined && value > field.max) count += 1
    }
    return count
  }, [localConfig])

  useBeforeUnloadGuard(dirtyCount > 0)

  const focusFirstInvalid = () => {
    const element = document.querySelector<HTMLElement>(
      '[data-config-input="true"][aria-invalid="true"]',
    )
    if (!element) return
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.focus()
  }

  const scrollToSection = (id: string) => {
    const element = document.getElementById(id)
    if (!element) return
    element.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setActiveSection(id)
  }

  const handleConfigChange = (section: ConfigSection, key: string, value: boolean | number) => {
    if (!localConfig) return
    setLocalConfig({
      ...localConfig,
      [section]: {
        ...(localConfig as unknown as Record<string, Record<string, unknown>>)[section],
        [key]: value,
      },
    })
    setSaveStatus('idle')
  }

  const handleSaveConfig = () => {
    if (!localConfig) return
    setSaveStatus('saving')
    patchConfig.mutate(localConfig, {
      onSuccess: () => {
        setSaveStatus('saved')
        setBaseline(structuredClone(localConfig))
        toast(t.config.saveSuccess, 'success')
        if (savedTimer.current) window.clearTimeout(savedTimer.current)
        savedTimer.current = window.setTimeout(() => setSaveStatus('idle'), 1800)
      },
      onError: (err) => {
        setSaveStatus('idle')
        toast(formatPatchError(err, t.config.saveFailed), 'error')
      },
    })
  }

  const handleResetConfig = () => {
    if (!baseline) return
    setLocalConfig(structuredClone(baseline))
    setSaveStatus('idle')
  }

  const cfg = localConfig as unknown as Record<string, Record<string, unknown>>

  return (
    <PageShell
      maxWidth="max-w-6xl"
      header={
        <div className="flex items-center justify-between gap-3">
          <PageTitle icon={<Sliders size={18} />} title={t.config.title} />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setGlossaryOpen(true)}
            className="flex shrink-0 items-center gap-1.5"
          >
            <BookOpen size={14} aria-hidden="true" />
            {copy.glossaryButton}
          </Button>
        </div>
      }
    >
      {isLoading ? (
        <CardSkeleton cols={2} />
      ) : error ? (
        <ErrorAlert
          message={t.config.loadFailed}
          onRetry={() => refetch()}
          retryLabel={t.common.retry}
        />
      ) : localConfig ? (
        <div className="space-y-6 pb-20">
          <WorkflowCard copy={copy} onNavigate={scrollToSection} />

          <nav aria-label={copy.navLabel} className="sticky top-0 z-20 -mx-1 px-1 py-2">
            <div className="flex gap-1 overflow-x-auto rounded-xl border border-[var(--border-default)] bg-[var(--surface-elevated)] p-1 shadow-warm-xs scrollbar-thin">
              {NAV_ITEMS.map((item) => {
                const active = activeSection === item.id
                return (
                  <a
                    key={item.id}
                    href={`#${item.id}`}
                    onClick={(event) => {
                      event.preventDefault()
                      scrollToSection(item.id)
                    }}
                    aria-current={active ? 'location' : undefined}
                    className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors duration-150 ${
                      active
                        ? 'bg-brand-100/70 text-brand-fg'
                        : 'text-[var(--text-secondary)] hover:bg-[var(--surface-inset)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    {copy[item.labelKey]}
                    {(dirtyByNav[item.id] ?? 0) > 0 && (
                      <span
                        aria-label={copy.navUnsaved}
                        title={copy.navUnsaved}
                        className="h-1.5 w-1.5 rounded-full bg-brand-500"
                      />
                    )}
                  </a>
                )
              })}
            </div>
          </nav>

          <div className="relative">
            <input
              type="text"
              value={fieldSearch}
              onChange={(e) => setFieldSearch(e.target.value)}
              placeholder={copy.fieldSearchPlaceholder}
              aria-label={copy.fieldSearchPlaceholder}
              className="w-full rounded-lg border border-[var(--border-default)] bg-surface-card px-3 py-2 pr-9 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)] focus-visible:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-200/30"
            />
            {fieldSearch && (
              <button
                type="button"
                onClick={() => setFieldSearch('')}
                aria-label={t.common.close}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-secondary)]"
              >
                ×
              </button>
            )}
          </div>

          {fieldSearch.trim() && (
            <p className="rounded-lg border border-[var(--border-default)] bg-surface-inset px-3 py-2 text-xs text-[var(--text-tertiary)]">
              {matchCount > 0
                ? translate(copy.fieldSearchMatches, { n: matchCount })
                : copy.fieldSearchEmpty}
            </p>
          )}

          <SectionGroup
            id="write-decision"
            accentFrom="from-brand-400"
            accentTo="to-brand-600"
            title={copy.groupWriteDecision}
          >
            <WriteDecisionCard />
          </SectionGroup>

          <SectionGroup
            id="write-policy"
            accentFrom="from-info/60"
            accentTo="to-info"
            title={copy.groupWritePolicy}
          >
            <WritePolicyCard />
          </SectionGroup>

          <SectionGroup
            id="features"
            accentFrom={featureFlagsTheme.accentFrom}
            accentTo={featureFlagsTheme.accentTo}
            title={copy.groupFeatures}
          >
            <ConfigCard
              searchQuery={fieldSearch}
              theme={featureFlagsTheme}
              subtitle={featureFlagsTheme.subtitle}
              columns={2}
              fields={featureFlagFields}
              section="parasitic_evolution"
              localConfig={cfg}
              onFieldChange={handleConfigChange}
              delay={0.1}
            />
          </SectionGroup>

          <SectionGroup
            id="thresholds"
            accentFrom={memoryTheme.accentFrom}
            accentTo={memoryTheme.accentTo}
            title={copy.groupThresholds}
          >
            <ConfigCard
              searchQuery={fieldSearch}
              theme={memoryTheme}
              subtitle={memoryTheme.subtitle}
              columns={2}
              fields={memoryFields}
              section="memory"
              localConfig={cfg}
              onFieldChange={handleConfigChange}
              delay={0.15}
            />
          </SectionGroup>

          <SectionGroup
            id="performance"
            accentFrom={performanceTheme.accentFrom}
            accentTo={performanceTheme.accentTo}
            title={copy.groupPerformance}
          >
            <div className="grid items-start gap-4 xl:grid-cols-2">
              <ConfigCard
                searchQuery={fieldSearch}
                theme={performanceTheme}
                subtitle={performanceTheme.subtitle}
                columns={1}
                fields={performanceFields}
                section="performance"
                localConfig={cfg}
                onFieldChange={handleConfigChange}
                delay={0.2}
              />
              <ConfigCard
                searchQuery={fieldSearch}
                theme={retrievalTheme}
                subtitle={retrievalTheme.subtitle}
                columns={1}
                fields={retrievalFields}
                section="retrieval"
                localConfig={cfg}
                onFieldChange={handleConfigChange}
                delay={0.25}
              />
            </div>
          </SectionGroup>

          <SectionGroup
            id="runtime"
            accentFrom={mcpTheme.accentFrom}
            accentTo={mcpTheme.accentTo}
            title={copy.groupRuntime}
          >
            <div className="grid items-start gap-4 xl:grid-cols-2">
              <ConfigCard
                searchQuery={fieldSearch}
                theme={mcpTheme}
                subtitle={mcpTheme.subtitle}
                columns={1}
                fields={mcpFields}
                section="mcp"
                localConfig={cfg}
                onFieldChange={handleConfigChange}
                delay={0.28}
              />
              <ConfigCard
                searchQuery={fieldSearch}
                theme={schedulerTheme}
                subtitle={schedulerTheme.subtitle}
                columns={1}
                fields={schedulerFields}
                section="scheduler"
                localConfig={cfg}
                onFieldChange={handleConfigChange}
                delay={0.3}
              />
            </div>
          </SectionGroup>

          <SectionGroup
            id="advanced"
            accentFrom="from-[var(--text-tertiary)]"
            accentTo="to-[var(--text-secondary)]"
            title={copy.groupAdvanced}
          >
            <ConfigCard
              searchQuery={fieldSearch}
              theme={advancedTheme}
              subtitle={advancedTheme.subtitle}
              columns={1}
              fields={advancedFields}
              section="app"
              localConfig={cfg}
              onFieldChange={handleConfigChange}
              delay={0.3}
            />
          </SectionGroup>
        </div>
      ) : null}

      <AnimatePresence>
        {dirtyCount > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 18 }}
            transition={{ ...spring.snappy }}
            className="fixed bottom-4 left-1/2 z-30 w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2"
          >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-[var(--border-default)] bg-[var(--surface-elevated)] px-4 py-3 shadow-warm-lg">
              <div className="min-w-0">
                <p
                  role="status"
                  aria-live="polite"
                  className="text-sm font-semibold text-[var(--text-primary)]"
                >
                  {translate(copy.pendingChanges, { n: dirtyCount })}
                </p>
                {invalidCount > 0 ? (
                  <button
                    type="button"
                    onClick={focusFirstInvalid}
                    className="mt-0.5 text-left text-[11px] font-medium text-danger-fg underline-offset-2 hover:underline"
                  >
                    {translate(copy.invalidParams, { n: invalidCount })}
                  </button>
                ) : (
                  <p className="mt-0.5 truncate text-[11px] font-medium text-[var(--text-tertiary)]">
                    {translate(copy.saveParamsHint, {
                      path: String(cfg.system_info?.config_path ?? ''),
                    })}
                  </p>
                )}
              </div>
              <div className="ml-auto flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleResetConfig}
                  disabled={saveStatus === 'saving'}
                >
                  <RotateCcw size={13} aria-hidden="true" />
                  {copy.discardChanges}
                </Button>
                <Button
                  size="sm"
                  onClick={handleSaveConfig}
                  disabled={saveStatus === 'saving' || patchConfig.isPending || invalidCount > 0}
                >
                  {saveStatus === 'saving' ? (
                    <Loader2 size={13} className="animate-spin" aria-hidden="true" />
                  ) : saveStatus === 'saved' ? (
                    <Check size={13} className="text-success-fg" aria-hidden="true" />
                  ) : (
                    <Save size={13} aria-hidden="true" />
                  )}
                  {saveStatus === 'saving'
                    ? t.config.saving
                    : saveStatus === 'saved'
                      ? t.config.saved
                      : copy.saveParams}
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <GlossaryDialog open={glossaryOpen} onOpenChange={setGlossaryOpen} copy={copy} />
    </PageShell>
  )
}
