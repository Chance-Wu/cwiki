import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Loader2,
  Save,
  Check,
  TrendingUp,
  Sliders,
  Info,
  Shield,
  Gauge,
  Search as SearchIcon,
  type LucideIcon,
} from 'lucide-react'
import { useTranslation } from '../i18n/I18nProvider'
import { spring, duration } from '../lib/motion'
import { CardSkeleton } from '../components/Skeleton'
import ErrorAlert from '../components/ErrorAlert'
import { useToast } from '../components/Toast'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import SectionGroup from '../components/SectionGroup'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Input } from '../components/ui/Input'
import { Switch } from '../components/ui/Switch'
import WriteDecisionCard from '../components/config/WriteDecisionCard'
import WritePolicyCard from '../components/config/WritePolicyCard'
import { useConfig } from '../hooks/useSettings'

// ── Schema types ────────────────────────────────────────────

type ConfigSection = 'app' | 'parasitic_evolution' | 'memory' | 'performance' | 'retrieval'

interface EditableField {
  key: string
  type: 'boolean' | 'number'
  nameKey: string
  descKey: string
  step?: string
}

interface ReadOnlyFieldSchema {
  key: string
  label: string
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

// ── Helpers ─────────────────────────────────────────────────

function camelCase(s: string): string {
  return s.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())
}

function toPascalCase(s: string): string {
  const c = camelCase(s)
  return c.charAt(0).toUpperCase() + c.slice(1)
}

// ── Field schemas ───────────────────────────────────────────

const featureFlagFields: EditableField[] = [
  'type_aware_freshness_enabled',
  'memory_gap_detection_enabled',
  'proactive_push_enabled',
  'memory_relations_enabled',
  'agent_profile_enabled',
  'memory_version_tracking_enabled',
  'auto_archive_enabled',
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
})

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
}))

const performanceFields: EditableField[] = [
  'context_cache_ttl',
  'context_cache_max_size',
  'context_token_budget',
  'dedup_top_k',
  'merge_suggestions_limit',
  'merge_suggestions_top_k',
  'merge_suggestions_threshold',
  'auto_consolidate_limit',
  'auto_consolidate_top_k',
].map((key) => ({
  key,
  type: 'number' as const,
  nameKey: `perf${toPascalCase(key)}`,
  descKey: `perf${toPascalCase(key)}Desc`,
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
  }
})

const systemInfoFields: ReadOnlyFieldSchema[] = [
  { key: 'embedding_model', label: 'embeddingModel' },
  { key: 'embedding_dimensions', label: 'embeddingDimensions' },
  { key: 'database_url', label: 'databaseUrl' },
  { key: 'api_host', label: 'apiHost' },
  { key: 'memory_dir', label: 'memoryDir' },
  { key: 'config_path', label: 'configPath' },
]

// ── Section themes ──────────────────────────────────────────

const featureTheme: SectionTheme = {
  title: 'groupFeatures',
  icon: Sliders,
  iconGradient: 'bg-gradient-to-br from-brand-50 to-brand-100/50',
  iconRing: 'ring-brand-200/40',
  iconColor: 'text-brand-fg',
  accentFrom: 'from-brand-400',
  accentTo: 'to-brand-600',
}

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
  grid: true,
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
  grid: true,
}

// ── Sub-components ──────────────────────────────────────────

function NumberInput({
  value,
  onChange,
  step,
}: {
  value: number
  onChange: (v: number) => void
  step?: string
}) {
  const [local, setLocal] = useState(String(value))
  const lastReported = useRef(value)
  if (value !== lastReported.current) {
    lastReported.current = value
    setLocal(String(value))
  }
  return (
    <Input
      type="text"
      inputMode="decimal"
      step={step}
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
      className="w-24 px-2.5 py-1.5 text-xs font-medium text-right tabular-nums"
    />
  )
}

function ReadOnlyField({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between py-2.5 rounded-lg px-3 -mx-3 hover:bg-brand-badge-bg transition-all duration-150">
      <span className="text-xs text-[var(--text-secondary)] font-medium">{label}</span>
      <span className="text-xs font-semibold text-[var(--text-primary)] font-mono bg-surface-elevated/40 px-2 py-0.5 rounded-lg ring-1 ring-[var(--border-default)]">
        {value}
      </span>
    </div>
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

function StaticIcon({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-surface-elevated/40 shrink-0 ring-1 ring-subtle">
      <Icon size={15} className="text-[var(--text-secondary)]" aria-hidden="true" />
    </div>
  )
}

function ConfigCard({
  theme,
  cardTitle,
  subtitle,
  fields,
  section,
  localConfig,
  onFieldChange,
  delay,
}: {
  theme: SectionTheme
  cardTitle?: string
  subtitle?: string
  fields: EditableField[]
  section: ConfigSection
  localConfig: Record<string, Record<string, unknown>>
  onFieldChange: (section: ConfigSection, key: string, value: boolean | number) => void
  delay: number
}) {
  const { t } = useTranslation()
  const titleKey = cardTitle ?? theme.title

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay }}
    >
      <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)]">
        <div className="flex items-center gap-2.5 mb-3">
          <AnimatedIcon theme={theme} />
          <h3 className="text-base font-semibold text-[var(--text-primary)]">
            {(t.config as Record<string, string>)[titleKey]}
          </h3>
        </div>
        {subtitle && (
          <p className="text-xs text-[var(--text-tertiary)] mb-4 font-medium">
            {(t.config as Record<string, string>)[subtitle]}
          </p>
        )}
        <div
          className={theme.grid ? 'grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2' : 'space-y-1'}
        >
          {fields.map((field) => (
            <div
              key={field.key}
              className="flex items-center justify-between py-2.5 rounded-lg px-3 -mx-3 hover:bg-brand-badge-bg transition-all duration-150"
            >
              <div className="flex-1 mr-3">
                <span className="text-xs text-[var(--text-primary)] font-medium">
                  {(t.config as Record<string, string>)[field.nameKey] ?? field.key}
                </span>
                <p className="text-xs text-[var(--text-tertiary)] font-medium">
                  {(t.config as Record<string, string>)[field.descKey] ?? ''}
                </p>
              </div>
              {field.type === 'boolean' ? (
                <Switch
                  checked={localConfig[section][field.key] as boolean}
                  onCheckedChange={(v) => onFieldChange(section, field.key, v)}
                />
              ) : (
                <NumberInput
                  value={(localConfig[section][field.key] as number) ?? 0}
                  onChange={(v) => onFieldChange(section, field.key, v)}
                  step={field.step}
                />
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
  const tc = t.config as Record<string, string>
  const { toast } = useToast()
  const { data: config, isLoading, error, refetch, patchConfig } = useConfig()

  const [localConfig, setLocalConfig] = useState<typeof config | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle')

  if (config && !localConfig) setLocalConfig(structuredClone(config))

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

  const handleSaveConfig = async () => {
    if (!localConfig) return
    setSaveStatus('saving')
    patchConfig.mutate(localConfig, {
      onSuccess: () => {
        setSaveStatus('saved')
        toast(t.config.saveSuccess, 'success')
      },
      onError: () => {
        setSaveStatus('idle')
        toast(t.config.saveFailed, 'error')
      },
    })
    setTimeout(() => setSaveStatus('idle'), 2000)
  }

  const cfg = localConfig as unknown as Record<string, Record<string, unknown>>

  return (
    <PageShell
      maxWidth="max-w-6xl"
      header={
        <div className="flex items-center justify-between">
          <PageTitle icon={<Sliders size={18} />} title={t.config.title} />
          <Button
            onClick={handleSaveConfig}
            disabled={saveStatus === 'saving' || !localConfig || patchConfig.isPending}
            variant="secondary"
            className="flex items-center gap-1.5"
          >
            <AnimatePresence mode="wait">
              {saveStatus === 'saved' ? (
                <motion.div
                  key="saved"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  transition={spring.snappy}
                  className="flex items-center gap-1.5"
                >
                  <Check size={14} className="text-success-fg" aria-hidden="true" />
                  <span>{t.config.saved}</span>
                </motion.div>
              ) : (
                <motion.div
                  key="save"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  transition={spring.snappy}
                  className="flex items-center gap-1.5"
                >
                  {saveStatus === 'saving' ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Save size={14} aria-hidden="true" />
                  )}
                  <span>{saveStatus === 'saving' ? t.config.saving : t.config.save}</span>
                </motion.div>
              )}
            </AnimatePresence>
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
        <div className="space-y-8">
          {/* ── 写入管理 ── */}
          <SectionGroup
            accentFrom="from-brand-400"
            accentTo="to-brand-600"
            title={tc.groupWriteDecision}
          >
            <WriteDecisionCard />
          </SectionGroup>

          {/* ── 写入后审核 ── */}
          <SectionGroup accentFrom="from-info/60" accentTo="to-info" title={tc.groupWritePolicy}>
            <WritePolicyCard />
          </SectionGroup>

          {/* ── 功能开关 ── */}
          <SectionGroup
            accentFrom={featureTheme.accentFrom}
            accentTo={featureTheme.accentTo}
            title={tc.groupFeatures}
          >
            <ConfigCard
              theme={featureTheme}
              cardTitle="appConfig"
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
              delay={0.05}
            />
            <ConfigCard
              theme={featureFlagsTheme}
              subtitle={featureFlagsTheme.subtitle}
              fields={featureFlagFields}
              section="parasitic_evolution"
              localConfig={cfg}
              onFieldChange={handleConfigChange}
              delay={0.1}
            />
          </SectionGroup>

          {/* ── 阈值参数 ── */}
          <SectionGroup
            accentFrom={memoryTheme.accentFrom}
            accentTo={memoryTheme.accentTo}
            title={tc.groupThresholds}
          >
            <ConfigCard
              theme={memoryTheme}
              subtitle={memoryTheme.subtitle}
              fields={memoryFields}
              section="memory"
              localConfig={cfg}
              onFieldChange={handleConfigChange}
              delay={0.15}
            />
          </SectionGroup>

          {/* ── 性能与检索 ── */}
          <SectionGroup
            accentFrom={performanceTheme.accentFrom}
            accentTo={performanceTheme.accentTo}
            title={tc.groupPerformance}
          >
            <ConfigCard
              theme={performanceTheme}
              subtitle={performanceTheme.subtitle}
              fields={performanceFields}
              section="performance"
              localConfig={cfg}
              onFieldChange={handleConfigChange}
              delay={0.2}
            />
            <ConfigCard
              theme={retrievalTheme}
              subtitle={retrievalTheme.subtitle}
              fields={retrievalFields}
              section="retrieval"
              localConfig={cfg}
              onFieldChange={handleConfigChange}
              delay={0.25}
            />
          </SectionGroup>

          {/* ── 系统信息（只读） ── */}
          <SectionGroup
            accentFrom="from-[var(--text-tertiary)]"
            accentTo="to-[var(--text-secondary)]"
            title={tc.groupSystemInfo}
          >
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring.snappy, delay: 0.3 }}
            >
              <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)] bg-surface-elevated/20">
                <div className="flex items-center gap-2.5 mb-3">
                  <StaticIcon icon={TrendingUp} />
                  <h3 className="text-base font-semibold text-[var(--text-primary)]">
                    {t.config.systemInfo}
                  </h3>
                </div>
                <p className="text-xs text-[var(--text-tertiary)] mb-4 font-medium">
                  {t.config.systemInfoDesc}
                </p>
                <div className="divide-y divide-[var(--border-default)]">
                  {systemInfoFields.map((field) => {
                    const rawValue = cfg.system_info[field.key]
                    const displayValue =
                      field.key === 'api_host'
                        ? `${rawValue}:${cfg.system_info.api_port}`
                        : (rawValue as string | number)
                    return (
                      <ReadOnlyField
                        key={field.key}
                        label={(t.config as Record<string, string>)[field.label]}
                        value={displayValue}
                      />
                    )
                  })}
                </div>
              </Card>
            </motion.div>
          </SectionGroup>
        </div>
      ) : null}
    </PageShell>
  )
}
