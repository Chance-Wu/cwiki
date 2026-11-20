// ConfigPage 的字段 schema、主题与共享工具：纯数据与纯函数，无 JSX。
// 从 ConfigPage.tsx 拆出；新增配置字段/主题只改这里，页面与卡片自动跟随。
import { Clock, Gauge, Info, Plug, Search as SearchIcon, Shield, Wrench } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

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
}

const PERFORMANCE_UNITS: Record<string, UnitKey> = {
  context_cache_ttl: 'seconds',
  context_cache_max_size: 'items',
  context_token_budget: 'tokens',
  dedup_top_k: 'items',
}

const featureFlagFields: EditableField[] = [
  'memory_gap_detection_enabled',
  'proactive_push_enabled',
  'memory_relations_enabled',
  'agent_profile_enabled',
  'memory_version_tracking_enabled',
  'review_reminders_enabled',
  'mastery_coupled_decay_enabled',
  'entity_extraction_enabled',
  'write_time_conflict_enabled',
  'episodic_retrieval_enabled',
].map((key) => ({
  key,
  type: 'boolean' as const,
  nameKey: `flagDesc${toPascalCase(key)}`,
  descKey: `flagDetail${toPascalCase(key)}`,
}))

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

// 自动批准策略：达到阈值的候选跳过人工审核；冲突与高重复仍强制拦截
const autoApproveFields: EditableField[] = [
  {
    key: 'auto_approve_enabled',
    type: 'boolean',
    nameKey: 'memAutoApproveEnabled',
    descKey: 'memAutoApproveEnabledDesc',
  },
  {
    key: 'auto_approve_gate_threshold',
    type: 'number',
    nameKey: 'memAutoApproveGateThreshold',
    descKey: 'memAutoApproveGateThresholdDesc',
    step: '0.01',
    unit: 'score',
    min: 0,
    max: 1,
  },
  {
    key: 'auto_approve_value_threshold',
    type: 'number',
    nameKey: 'memAutoApproveValueThreshold',
    descKey: 'memAutoApproveValueThresholdDesc',
    step: '0.01',
    unit: 'score',
    min: 0,
    max: 1,
  },
  {
    key: 'auto_approve_confidence_threshold',
    type: 'number',
    nameKey: 'memAutoApproveConfidenceThreshold',
    descKey: 'memAutoApproveConfidenceThresholdDesc',
    step: '0.01',
    unit: 'score',
    min: 0,
    max: 1,
  },
  {
    key: 'auto_approve_duplicate_threshold',
    type: 'number',
    nameKey: 'memAutoApproveDuplicateThreshold',
    descKey: 'memAutoApproveDuplicateThresholdDesc',
    step: '0.01',
    unit: 'score',
    min: 0,
    max: 1,
  },
]

memoryFields.push(...autoApproveFields)

const performanceFields: EditableField[] = [
  'context_cache_ttl',
  'context_cache_max_size',
  'context_token_budget',
  'dedup_top_k',
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
  'reranker_bm25_weight',
  'reranker_confidence_weight',
  'reranker_importance_weight',
  'reranker_freshness_weight',
  'reranker_usage_weight',
  'reranker_intent_weight',
  'reranker_key_term_bonus',
  'reranker_relevance_band',
].map((key) => {
  const suffix =
    key === 'reranker_relevance_band'
      ? 'relevanceBand'
      : key === 'reranker_bm25_weight'
        ? 'rerankBm25'
        : key.replace(/^reranker_/, '').replace(/_weight$/, '')
  return {
    key,
    type: 'number' as const,
    nameKey: `weight${toPascalCase(suffix)}`,
    descKey: `weight${toPascalCase(suffix)}Desc`,
    step: '0.01',
    unit: (key === 'reranker_key_term_bonus' ? 'bonus' : 'weight') as UnitKey,
    min: 0,
    max: key === 'reranker_relevance_band' ? 1 : 10,
  }
})

retrievalFields.push({
  key: 'auto_recall_enabled',
  type: 'boolean',
  nameKey: 'autoRecallEnabled',
  descKey: 'autoRecallEnabledDesc',
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
  iconColor: 'text-secondary',
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

const advancedFields: EditableField[] = [
  { key: 'debug', type: 'boolean', nameKey: 'debugMode', descKey: 'debugModeDesc' },
]

// 所有可搜索字段的扁平索引，用于判断全局是否有匹配
const ALL_SEARCHABLE_FIELDS: EditableField[] = [
  ...featureFlagFields,
  ...memoryFields,
  ...performanceFields,
  ...retrievalFields,
  ...mcpFields,
  ...schedulerFields,
  ...advancedFields,
]

function fieldMatches(field: EditableField, query: string, copy: Record<string, string>): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const name = (copy[field.nameKey] ?? field.key).toLowerCase()
  const desc = (copy[field.descKey] ?? '').toLowerCase()
  return name.includes(q) || desc.includes(q) || field.key.toLowerCase().includes(q)
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

export {
  EDITABLE_SECTIONS,
  UNIT_KEYS,
  NAV_ITEMS,
  WORKFLOW_STEPS,
  GLOSSARY,
  PERFORMANCE_RANGES,
  PERFORMANCE_UNITS,
  featureFlagFields,
  memoryFields,
  autoApproveFields,
  performanceFields,
  retrievalFields,
  mcpFields,
  schedulerFields,
  advancedFields,
  NUMERIC_FIELDS,
  featureFlagsTheme,
  advancedTheme,
  memoryTheme,
  performanceTheme,
  retrievalTheme,
  mcpTheme,
  schedulerTheme,
  ALL_SEARCHABLE_FIELDS,
}
export type { ConfigSection, UnitKey, EditableField, SectionTheme }
export { camelCase, toPascalCase, formatPatchError, fieldMatches }
