import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  Clock,
  Gauge,
  Info,
  Loader2,
  Plug,
  RotateCcw,
  Save,
  Search as SearchIcon,
  Shield,
  Sliders,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { translate, useTranslation } from '../i18n/I18nProvider'
import { duration, spring } from '../lib/motion'
import { CardSkeleton } from '../components/Skeleton'
import ErrorAlert from '../components/ErrorAlert'
import { useToast } from '../components/Toast'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import SectionGroup from '../components/SectionGroup'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Dialog } from '../components/ui/Dialog'
import { Input } from '../components/ui/Input'
import { Switch } from '../components/ui/Switch'
import WriteDecisionCard from '../components/config/WriteDecisionCard'
import WritePolicyCard from '../components/config/WritePolicyCard'
import { useConfig } from '../hooks/useSettings'
import { useBeforeUnloadGuard } from '../hooks/useBeforeUnload'
import type { ConfigData } from '../lib/api'

// ── Schema types ────────────────────────────────────────────

type ConfigSection =
  'app' | 'parasitic_evolution' | 'memory' | 'performance' | 'retrieval' | 'mcp' | 'scheduler'
type UnitKey = 'chars' | 'seconds' | 'items' | 'tokens' | 'score' | 'weight' | 'bonus' | 'hours'

const EDITABLE_SECTIONS: ConfigSection[] = [
  'app',
  'parasitic_evolution',
  'memory',
  'performance',
  'retrieval',
  'mcp',
  'scheduler',
]

const UNIT_KEYS: Record<UnitKey, string> = {
  chars: 'unitChars',
  seconds: 'unitSeconds',
  items: 'unitItems',
  tokens: 'unitTokens',
  score: 'unitScore',
  weight: 'unitWeight',
  bonus: 'unitBonus',
  hours: 'unitHours',
}

interface EditableField {
  key: string
  type: 'boolean' | 'number'
  nameKey: string
  descKey: string
  step?: string
  unit?: UnitKey
  min?: number
  max?: number
}

interface SectionTheme {
  title: string
  icon: LucideIcon
  iconGradient: string
  iconRing: string
  iconColor: string
  accentFrom: string
  accentTo: string
  grid?: boolean
  subtitle?: string
}

const NAV_ITEMS = [
  { id: 'write-decision', labelKey: 'navWriteDecision' },
  { id: 'write-policy', labelKey: 'navWritePolicy' },
  { id: 'features', labelKey: 'navFeatures' },
  { id: 'thresholds', labelKey: 'navThresholds' },
  { id: 'performance', labelKey: 'navPerformance' },
  { id: 'runtime', labelKey: 'navRuntime' },
  { id: 'advanced', labelKey: 'navAdvanced' },
]

const WORKFLOW_STEPS = [
  {
    id: 'write-decision',
    labelKey: 'workflowStep1Label',
    titleKey: 'workflowStep1Title',
    descKey: 'workflowStep1Desc',
    chip: 'border-danger/40 bg-danger/10 text-danger-fg',
  },
  {
    id: 'write-policy',
    labelKey: 'workflowStep2Label',
    titleKey: 'workflowStep2Title',
    descKey: 'workflowStep2Desc',
    chip: 'border-info/40 bg-info/10 text-info-fg',
  },
  {
    id: 'features',
    labelKey: 'workflowStep3Label',
    titleKey: 'workflowStep3Title',
    descKey: 'workflowStep3Desc',
    chip: 'border-success/40 bg-success/10 text-success-fg',
  },
]

const GLOSSARY: Array<[string, string]> = [
  ['glossaryAdmission', 'glossaryAdmissionDesc'],
  ['glossaryReview', 'glossaryReviewDesc'],
  ['glossaryCandidate', 'glossaryCandidateDesc'],
  ['glossaryWorkspace', 'glossaryWorkspaceDesc'],
  ['glossaryBm25', 'glossaryBm25Desc'],
  ['glossaryVector', 'glossaryVectorDesc'],
  ['glossaryRrf', 'glossaryRrfDesc'],
  ['glossaryThreshold', 'glossaryThresholdDesc'],
  ['glossaryConsolidate', 'glossaryConsolidateDesc'],
  ['glossaryMastery', 'glossaryMasteryDesc'],
  ['glossaryEpisodic', 'glossaryEpisodicDesc'],
]

// ── Helpers ─────────────────────────────────────────────────

function camelCase(s: string): string {
  return s.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())
}

function toPascalCase(s: string): string {
  const c = camelCase(s)
  return c.charAt(0).toUpperCase() + c.slice(1)
}

interface ValidationDetail {
  loc?: unknown[]
  msg?: unknown
}

function formatPatchError(err: unknown, fallback: string): string {
  if (!(err instanceof Error)) return fallback
  try {
    const parsed: unknown = JSON.parse(err.message)
    if (Array.isArray(parsed)) {
      const parts = (parsed as ValidationDetail[])
        .map((item) => {
          const loc = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
          const msg = typeof item.msg === 'string' ? item.msg : ''
          return [loc, msg].filter(Boolean).join(': ')
        })
        .filter(Boolean)
      if (parts.length > 0) return parts.join('；')
    }
  } catch {
    /* 不是结构化校验错误时退回原始消息 */
  }
  return err.message || fallback
}

// ── Field schemas ───────────────────────────────────────────

const PERFORMANCE_RANGES: Record<string, [number, number]> = {
  context_cache_ttl: [0, 86400],
  context_cache_max_size: [1, 100_000],
  context_token_budget: [64, 200_000],
  dedup_top_k: [1, 1_000],
  merge_suggestions_threshold: [0, 1],
  auto_consolidate_limit: [1, 100_000],
  auto_consolidate_top_k: [1, 1_000],
}

const PERFORMANCE_UNITS: Record<string, UnitKey> = {
  context_cache_ttl: 'seconds',
  context_cache_max_size: 'items',
  context_token_budget: 'tokens',
  dedup_top_k: 'items',
  merge_suggestions_threshold: 'score',
  auto_consolidate_limit: 'items',
  auto_consolidate_top_k: 'items',
}

const featureFlagFields: EditableField[] = [
  'memory_gap_detection_enabled',
  'proactive_push_enabled',
  'memory_relations_enabled',
  'agent_profile_enabled',
  'memory_version_tracking_enabled',
  'auto_consolidate_enabled',
  'review_reminders_enabled',
  'mastery_coupled_decay_enabled',
  'entity_extraction_enabled',
  'write_time_conflict_enabled',
  'auto_merge_enabled',
  'episodic_retrieval_enabled',
].map((key) => ({
  key,
  type: 'boolean' as const,
  nameKey: `flagDesc${toPascalCase(key)}`,
  descKey: `flagDetail${toPascalCase(key)}`,
}))

featureFlagFields.push({
  key: 'auto_merge_threshold',
  type: 'number',
  nameKey: 'flagDescAutoMergeThreshold',
  descKey: 'flagDetailAutoMergeThreshold',
  step: '0.01',
  unit: 'score',
  min: 0,
  max: 1,
})

featureFlagFields.push(
  {
    key: 'auto_relation_enabled',
    type: 'boolean',
    nameKey: 'flagDescAutoRelationEnabled',
    descKey: 'flagDetailAutoRelationEnabled',
  },
  {
    key: 'auto_relation_threshold',
    type: 'number',
    nameKey: 'flagDescAutoRelationThreshold',
    descKey: 'flagDetailAutoRelationThreshold',
    step: '0.01',
    unit: 'score',
    min: 0,
    max: 1,
  },
  {
    key: 'auto_relation_max_per_memory',
    type: 'number',
    nameKey: 'flagDescAutoRelationMaxPerMemory',
    descKey: 'flagDetailAutoRelationMaxPerMemory',
    step: '1',
    unit: 'items',
    min: 1,
    max: 100,
  },
  {
    key: 'relation_auto_edge_ttl_days',
    type: 'number',
    nameKey: 'flagDescRelationAutoEdgeTtlDays',
    descKey: 'flagDetailRelationAutoEdgeTtlDays',
    step: '1',
    min: 0,
    max: 3650,
  },
)

const memoryFields: EditableField[] = [
  { key: 'title_max_length', step: '1' },
  { key: 'consolidate_threshold' },
  { key: 'similarity_threshold' },
  { key: 'relation_merge_threshold' },
  { key: 'relation_update_threshold' },
  { key: 'relation_conflict_threshold' },
  { key: 'priority_discard_threshold' },
  { key: 'priority_low_threshold' },
  { key: 'priority_high_threshold' },
].map((f) => ({
  ...f,
  type: 'number' as const,
  nameKey: `mem${toPascalCase(f.key)}`,
  descKey: `mem${toPascalCase(f.key)}Desc`,
  unit: (f.key === 'title_max_length' ? 'chars' : 'score') as UnitKey,
  min: f.key === 'title_max_length' ? 1 : 0,
  max: f.key === 'title_max_length' ? 500 : 1,
}))

memoryFields.push(
  {
    key: 'auto_create_workspace',
    type: 'boolean',
    nameKey: 'memAutoCreateWorkspace',
    descKey: 'memAutoCreateWorkspaceDesc',
  },
  {
    key: 'duplicate_exact_threshold',
    type: 'number',
    nameKey: 'memDuplicateExactThreshold',
    descKey: 'memDuplicateExactThresholdDesc',
    step: '0.01',
    unit: 'score',
    min: 0,
    max: 1,
  },
  {
    key: 'duplicate_possible_threshold',
    type: 'number',
    nameKey: 'memDuplicatePossibleThreshold',
    descKey: 'memDuplicatePossibleThresholdDesc',
    step: '0.01',
    unit: 'score',
    min: 0,
    max: 1,
  },
  {
    key: 'submit_dedup_scan_limit',
    type: 'number',
    nameKey: 'memSubmitDedupScanLimit',
    descKey: 'memSubmitDedupScanLimitDesc',
    step: '100',
    unit: 'items',
    min: 1,
    max: 100_000,
  },
  {
    key: 'submit_dedup_cross_workspace',
    type: 'boolean',
    nameKey: 'memSubmitDedupCrossWorkspace',
    descKey: 'memSubmitDedupCrossWorkspaceDesc',
  },
)

const performanceFields: EditableField[] = [
  'context_cache_ttl',
  'context_cache_max_size',
  'context_token_budget',
  'dedup_top_k',
  'merge_suggestions_threshold',
  'auto_consolidate_limit',
  'auto_consolidate_top_k',
].map((key) => ({
  key,
  type: 'number' as const,
  nameKey: `perf${toPascalCase(key)}`,
  descKey: `perf${toPascalCase(key)}Desc`,
  unit: PERFORMANCE_UNITS[key],
  min: PERFORMANCE_RANGES[key]?.[0],
  max: PERFORMANCE_RANGES[key]?.[1],
}))

const retrievalFields: EditableField[] = [
  'bm25_weight',
  'vector_weight',
  'reranker_rrf_weight',
  'reranker_semantic_weight',
  'reranker_confidence_weight',
  'reranker_importance_weight',
  'reranker_freshness_weight',
  'reranker_usage_weight',
  'reranker_intent_weight',
  'reranker_key_term_bonus',
].map((key) => {
  const suffix = key.replace(/^reranker_/, '').replace(/_weight$/, '')
  return {
    key,
    type: 'number' as const,
    nameKey: `weight${toPascalCase(suffix)}`,
    descKey: `weight${toPascalCase(suffix)}Desc`,
    step: '0.01',
    unit: (key === 'reranker_key_term_bonus' ? 'bonus' : 'weight') as UnitKey,
    min: 0,
    max: 10,
  }
})

const mcpFields: EditableField[] = [
  {
    key: 'max_retries',
    type: 'number',
    nameKey: 'mcpMaxRetries',
    descKey: 'mcpMaxRetriesDesc',
    step: '1',
    unit: 'items',
    min: 0,
    max: 10,
  },
  {
    key: 'retry_backoff_seconds',
    type: 'number',
    nameKey: 'mcpRetryBackoffSeconds',
    descKey: 'mcpRetryBackoffSecondsDesc',
    step: '0.1',
    unit: 'seconds',
    min: 0,
    max: 60,
  },
]

const schedulerFields: EditableField[] = [
  {
    key: 'auto_relation_interval_hours',
    type: 'number',
    nameKey: 'schedulerAutoRelationIntervalHours',
    descKey: 'schedulerAutoRelationIntervalHoursDesc',
    step: '1',
    unit: 'hours',
    min: 0,
    max: 720,
  },
  {
    key: 'relation_ttl_check_interval_hours',
    type: 'number',
    nameKey: 'schedulerRelationTtlCheckIntervalHours',
    descKey: 'schedulerRelationTtlCheckIntervalHoursDesc',
    step: '1',
    unit: 'hours',
    min: 0,
    max: 720,
  },
]

const NUMERIC_FIELDS: Array<EditableField & { section: ConfigSection }> = [
  ...featureFlagFields
    .filter((field) => field.type === 'number')
    .map((field) => ({
      ...field,
      section: 'parasitic_evolution' as const,
    })),
  ...memoryFields.map((field) => ({ ...field, section: 'memory' as const })),
  ...performanceFields.map((field) => ({ ...field, section: 'performance' as const })),
  ...retrievalFields.map((field) => ({ ...field, section: 'retrieval' as const })),
  ...mcpFields.map((field) => ({ ...field, section: 'mcp' as const })),
  ...schedulerFields.map((field) => ({ ...field, section: 'scheduler' as const })),
]

// ── Section themes ──────────────────────────────────────────

const featureFlagsTheme: SectionTheme = {
  title: 'featureFlags',
  icon: Shield,
  iconGradient: 'bg-gradient-to-br from-warning/18 to-warning/8',
  iconRing: 'ring-warning/30',
  iconColor: 'text-warning-fg',
  accentFrom: 'from-brand-400',
  accentTo: 'to-brand-600',
  subtitle: 'featureFlagsSubtitle',
}

const advancedTheme: SectionTheme = {
  title: 'appConfig',
  icon: Wrench,
  iconGradient: 'bg-gradient-to-br from-[var(--surface-elevated)] to-[var(--surface-inset)]',
  iconRing: 'ring-subtle',
  iconColor: 'text-[var(--text-secondary)]',
  accentFrom: 'from-[var(--text-tertiary)]',
  accentTo: 'to-[var(--text-secondary)]',
  subtitle: 'appConfigDesc',
}

const memoryTheme: SectionTheme = {
  title: 'memoryConfig',
  icon: Info,
  iconGradient: 'bg-gradient-to-br from-info/18 to-info/8',
  iconRing: 'ring-info/30',
  iconColor: 'text-info-fg',
  accentFrom: 'from-info/60',
  accentTo: 'to-info',
  subtitle: 'memoryDesc',
  grid: true,
}

const performanceTheme: SectionTheme = {
  title: 'performanceConfig',
  icon: Gauge,
  iconGradient: 'bg-gradient-to-br from-success/18 to-success/8',
  iconRing: 'ring-success/30',
  iconColor: 'text-success-fg',
  accentFrom: 'from-success/60',
  accentTo: 'to-success',
  subtitle: 'performanceDesc',
}

const retrievalTheme: SectionTheme = {
  title: 'retrievalConfig',
  icon: SearchIcon,
  iconGradient: 'bg-gradient-to-br from-brand-50 to-brand-100/50',
  iconRing: 'ring-brand-200/40',
  iconColor: 'text-brand-fg',
  accentFrom: 'from-success/60',
  accentTo: 'to-success',
  subtitle: 'retrievalDesc',
}

const mcpTheme: SectionTheme = {
  title: 'mcpConfig',
  icon: Plug,
  iconGradient: 'bg-gradient-to-br from-info/18 to-info/8',
  iconRing: 'ring-info/30',
  iconColor: 'text-info-fg',
  accentFrom: 'from-info/60',
  accentTo: 'to-info',
  subtitle: 'mcpConfigDesc',
}

const schedulerTheme: SectionTheme = {
  title: 'schedulerConfig',
  icon: Clock,
  iconGradient: 'bg-gradient-to-br from-warning/18 to-warning/8',
  iconRing: 'ring-warning/30',
  iconColor: 'text-warning-fg',
  accentFrom: 'from-warning/60',
  accentTo: 'to-warning',
  subtitle: 'schedulerConfigDesc',
}

// ── Sub-components ──────────────────────────────────────────

function NumberInput({
  value,
  onChange,
  step,
  min,
  max,
  rangeLabel,
}: {
  value: number
  onChange: (v: number) => void
  step?: string
  min?: number
  max?: number
  rangeLabel?: string
}) {
  const [local, setLocal] = useState(String(value))
  const lastReported = useRef(value)
  if (value !== lastReported.current) {
    lastReported.current = value
    setLocal(String(value))
  }
  const numeric = Number(local)
  const invalid =
    local.trim() !== '' &&
    !Number.isNaN(numeric) &&
    ((min !== undefined && numeric < min) || (max !== undefined && numeric > max))

  return (
    <Input
      type="text"
      inputMode="decimal"
      step={step}
      aria-invalid={invalid}
      data-config-input="true"
      title={invalid ? rangeLabel : undefined}
      value={local}
      onChange={(e) => {
        const raw = e.target.value
        if (raw === '' || raw === '-' || raw === '.') {
          setLocal(raw)
          return
        }
        if (!isNaN(Number(raw))) {
          setLocal(raw)
          const n = Number(raw)
          lastReported.current = n
          onChange(n)
        }
      }}
      onBlur={() => {
        const n = Number(local)
        if (isNaN(n)) setLocal(String(value))
        else setLocal(String(n))
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
      }}
      className={`w-20 px-2.5 py-1.5 text-right text-xs font-medium tabular-nums ${
        invalid ? 'border-danger/60 focus-visible:border-danger focus-visible:ring-danger/20' : ''
      }`}
    />
  )
}

function AnimatedIcon({ theme }: { theme: SectionTheme }) {
  const Icon = theme.icon
  return (
    <motion.div
      className={`flex items-center justify-center w-8 h-8 rounded-lg ${theme.iconGradient} shrink-0 ring-1 ${theme.iconRing}`}
      whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
      transition={{ duration: duration.modal }}
    >
      <Icon size={15} className={theme.iconColor} aria-hidden="true" />
    </motion.div>
  )
}

function WorkflowCard({
  copy,
  onNavigate,
}: {
  copy: Record<string, string>
  onNavigate: (id: string) => void
}) {
  return (
    <Card className="p-4 md:p-5">
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">{copy.workflowTitle}</h3>
      <p className="mt-1 max-w-3xl text-xs font-medium leading-relaxed text-[var(--text-tertiary)]">
        {copy.workflowHint}
      </p>
      <div className="mt-4 grid gap-2 md:grid-cols-3">
        {WORKFLOW_STEPS.map((step, index) => (
          <div key={step.id} className="relative">
            <button
              type="button"
              onClick={() => onNavigate(step.id)}
              className="group flex h-full w-full flex-col rounded-xl border border-[var(--border-default)] bg-surface-card/60 p-3 text-left transition-colors duration-150 hover:border-brand-300/60 hover:bg-brand-50/40 dark:hover:bg-brand-500/5"
            >
              <span className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-md border text-[11px] font-semibold tabular-nums ${step.chip}`}
                >
                  {index + 1}
                </span>
                {copy[step.labelKey]}
              </span>
              <span className="mt-1.5 text-sm font-semibold text-[var(--text-primary)]">
                {copy[step.titleKey]}
              </span>
              <span className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                {copy[step.descKey]}
              </span>
              <span className="mt-2 flex items-center gap-1 text-[11px] font-medium text-brand-fg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                {copy.workflowOpen}
                <ArrowRight size={11} aria-hidden="true" />
              </span>
            </button>
            {index < WORKFLOW_STEPS.length - 1 && (
              <ChevronRight
                size={14}
                aria-hidden="true"
                className="absolute -right-2 top-1/2 hidden -translate-y-1/2 text-[var(--text-tertiary)] md:block"
              />
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

function GlossaryDialog({
  open,
  onOpenChange,
  copy,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  copy: Record<string, string>
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.glossaryTitle}
      description={copy.glossaryDesc}
      size="lg"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {GLOSSARY.map(([termKey, descKey]) => (
          <div
            key={termKey}
            className="rounded-lg border border-[var(--border-default)] bg-[var(--surface-inset)]/60 p-3"
          >
            <p className="text-xs font-semibold text-[var(--text-primary)]">{copy[termKey]}</p>
            <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
              {copy[descKey]}
            </p>
          </div>
        ))}
      </div>
    </Dialog>
  )
}

function ConfigCard({
  theme,
  cardTitle,
  subtitle,
  fields,
  columns,
  section,
  localConfig,
  onFieldChange,
  delay,
}: {
  theme: SectionTheme
  cardTitle?: string
  subtitle?: string
  fields: EditableField[]
  columns?: 1 | 2
  section: ConfigSection
  localConfig: Record<string, Record<string, unknown>>
  onFieldChange: (section: ConfigSection, key: string, value: boolean | number) => void
  delay: number
}) {
  const { t } = useTranslation()
  const copy = t.config as Record<string, string>
  const titleKey = cardTitle ?? theme.title
  const columnCount = columns ?? (theme.grid ? 2 : 1)

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay }}
      className="h-full"
    >
      <Card className="h-full p-4 transition-all duration-150 hover:border-[var(--border-strong)] hover:shadow-warm-md md:p-5">
        <div className="mb-3 flex items-center gap-2.5">
          <AnimatedIcon theme={theme} />
          <h3 className="text-base font-semibold text-[var(--text-primary)]">
            {copy[titleKey] ?? titleKey}
          </h3>
        </div>
        {subtitle && (
          <p className="mb-4 text-xs font-medium text-[var(--text-tertiary)]">
            {copy[subtitle] ?? subtitle}
          </p>
        )}
        <div
          className={
            columnCount === 2
              ? 'grid grid-cols-1 gap-x-6 gap-y-1 md:grid-cols-2'
              : 'flex flex-col gap-y-1'
          }
        >
          {fields.map((field) => (
            <div
              key={field.key}
              className="flex items-center justify-between rounded-lg px-3 py-2.5 -mx-3 transition-all duration-150 hover:bg-brand-badge-bg"
            >
              <div className="mr-3 min-w-0 flex-1">
                <span className="text-xs font-medium text-[var(--text-primary)]">
                  {copy[field.nameKey] ?? field.key}
                </span>
                <p className="text-xs font-medium text-[var(--text-tertiary)]">
                  {copy[field.descKey] ?? ''}
                </p>
              </div>
              {field.type === 'boolean' ? (
                <Switch
                  checked={localConfig[section][field.key] as boolean}
                  onCheckedChange={(v) => onFieldChange(section, field.key, v)}
                />
              ) : (
                <div className="flex shrink-0 items-center gap-1.5">
                  <NumberInput
                    value={(localConfig[section][field.key] as number) ?? 0}
                    onChange={(v) => onFieldChange(section, field.key, v)}
                    step={field.step}
                    min={field.min}
                    max={field.max}
                    rangeLabel={
                      field.min !== undefined && field.max !== undefined
                        ? translate(copy.fieldRange, { min: field.min, max: field.max })
                        : undefined
                    }
                  />
                  <span className="w-10 text-right text-[10px] font-medium tabular-nums text-[var(--text-tertiary)]">
                    {field.unit ? (copy[UNIT_KEYS[field.unit]] ?? '') : ''}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>
    </motion.div>
  )
}

// ── Main component ──────────────────────────────────────────

export default function ConfigPage() {
  const { t } = useTranslation()
  const copy = t.config as Record<string, string>
  const { toast } = useToast()
  const { data: config, isLoading, error, refetch, patchConfig } = useConfig()

  const [localConfig, setLocalConfig] = useState<ConfigData | null>(null)
  const [baseline, setBaseline] = useState<ConfigData | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [glossaryOpen, setGlossaryOpen] = useState(false)
  const [activeSection, setActiveSection] = useState(NAV_ITEMS[0].id)
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
              theme={advancedTheme}
              subtitle={advancedTheme.subtitle}
              columns={1}
              fields={[
                {
                  key: 'debug',
                  type: 'boolean',
                  nameKey: 'debugMode',
                  descKey: 'debugModeDesc',
                },
              ]}
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
