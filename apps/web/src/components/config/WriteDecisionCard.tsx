import { useEffect, useId, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, ListChecks, Loader2, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { duration, ease } from '../../lib/motion'
import { translate, useTranslation } from '../../i18n/I18nProvider'
import type {
  WriteDecisionAction,
  WriteDecisionData,
  WriteDecisionRule,
  WritePolicyRuleMatch,
} from '../../lib/api'
import { useWriteDecision } from '../../hooks/useSettings'
import ErrorAlert from '../ErrorAlert'
import { useToast } from '../Toast'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Input } from '../ui/Input'
import { SegmentedControl } from '../ui/SegmentedControl'
import { Switch } from '../ui/Switch'
import { Textarea } from '../ui/Textarea'
import { LinesInput, MatchChips, MatchEditor } from './writeRuleShared'
import { isEmptyMatch, validateRuleIds } from './writeRuleUtils'

interface GroupMeta {
  action: WriteDecisionAction
  titleKey: string
  descKey: string
  addKey: string
  badgeVariant: 'success' | 'danger' | 'info'
  panelClass: string
  titleClass: string
}

const GROUPS: Record<WriteDecisionAction, GroupMeta> = {
  write: {
    action: 'write',
    titleKey: 'writeDecisionGroupWrite',
    descKey: 'writeDecisionGroupWriteDesc',
    addKey: 'writeDecisionAddWrite',
    badgeVariant: 'success',
    panelClass: 'border-success/30 bg-success/10',
    titleClass: 'text-success-fg',
  },
  skip: {
    action: 'skip',
    titleKey: 'writeDecisionGroupSkip',
    descKey: 'writeDecisionGroupSkipDesc',
    addKey: 'writeDecisionAddSkip',
    badgeVariant: 'danger',
    panelClass: 'border-danger/30 bg-danger/10',
    titleClass: 'text-danger-fg',
  },
  update: {
    action: 'update',
    titleKey: 'writeDecisionGroupUpdate',
    descKey: 'writeDecisionGroupUpdateDesc',
    addKey: 'writeDecisionAddUpdate',
    badgeVariant: 'info',
    panelClass: 'border-info/30 bg-info/10',
    titleClass: 'text-info-fg',
  },
}

// 服务端按“不写入 > 更新 > 写入”固定优先级匹配；配置也按此顺序落盘
const PRIORITY_ORDER: WriteDecisionAction[] = ['skip', 'update', 'write']

const ACTION_LABEL_KEYS: Record<WriteDecisionAction, string> = {
  write: 'writeDecisionActionWrite',
  skip: 'writeDecisionActionSkip',
  update: 'writeDecisionActionUpdate',
}

function buildPreview(policy: WriteDecisionData, copy: Record<string, string>): string {
  if (!policy.enabled) return ''
  const defaultLabel =
    policy.default_action === 'skip'
      ? copy.writeDecisionDefaultSkip
      : copy.writeDecisionDefaultWrite
  const header = `cwiki 写入决策（优先级：不写入 > 更新 > 写入；未命中：${defaultLabel}）：`
  const rules = [...policy.rules].sort(
    (a, b) => PRIORITY_ORDER.indexOf(a.action) - PRIORITY_ORDER.indexOf(b.action),
  )
  const lines = rules.map((rule) => {
    const actionLabel = copy[ACTION_LABEL_KEYS[rule.action]]
    const description = (rule.description.trim() || rule.id).slice(0, 120)
    const examples = rule.examples.slice(0, 2).map((item) => item.slice(0, 80))
    return `- [${actionLabel}] ${description}${examples.length ? `｜例：${examples.join('；')}` : ''}`
  })
  if (lines.length === 0) {
    lines.push('（未配置规则，按 cwiki-save skill 判断）')
  }
  const footer =
    '\n规则只决定是否写入/更新；写入后的审核在 write_policy 中配置，查重与格式仍遵循 cwiki-save skill。'
  return (header + '\n' + lines.join('\n') + footer).slice(0, 800)
}

function RuleEditor({
  rule,
  error,
  copy,
  onChange,
  onMatchChange,
}: {
  rule: WriteDecisionRule
  error: string | null
  copy: Record<string, string>
  onChange: (patch: Partial<WriteDecisionRule>) => void
  onMatchChange: (key: keyof WritePolicyRuleMatch, values: string[]) => void
}) {
  const idInputId = useId()
  const descriptionId = useId()

  return (
    <div className="space-y-4">
      <div>
        <label
          htmlFor={idInputId}
          className="block text-xs font-medium text-[var(--text-secondary)]"
        >
          {copy.writePolicyRuleId}
        </label>
        <Input
          id={idInputId}
          value={rule.id}
          onChange={(event) => onChange({ id: event.target.value })}
          placeholder={copy.writePolicyRuleIdPlaceholder}
          className="mt-1.5 font-mono"
          aria-invalid={Boolean(error)}
        />
        {error && <p className="mt-1 text-xs text-danger-fg">{error}</p>}
      </div>

      <div>
        <label
          htmlFor={descriptionId}
          className="block text-xs font-medium text-[var(--text-secondary)]"
        >
          {copy.writeDecisionDescription}
        </label>
        <Textarea
          id={descriptionId}
          value={rule.description}
          onChange={(event) => onChange({ description: event.target.value })}
          placeholder={copy.writeDecisionDescriptionPlaceholder}
          rows={2}
          className="mt-1.5"
        />
      </div>

      <LinesInput
        label={copy.writeDecisionExamples}
        value={rule.examples}
        onChange={(values) => onChange({ examples: values })}
        placeholder={copy.writeDecisionExamplesPlaceholder}
        hint={copy.writeDecisionExamplesHint}
      />

      <MatchEditor
        match={rule.match}
        onMatchChange={onMatchChange}
        hint={copy.writePolicyMatchHint}
        warning={copy.writeDecisionCatchAllWarning}
        copy={copy}
      />
    </div>
  )
}

export default function WriteDecisionCard() {
  const { t } = useTranslation()
  const copy = t.config as Record<string, string>
  const { toast } = useToast()
  const { data, isLoading, error, refetch, update } = useWriteDecision()

  const [draft, setDraft] = useState<WriteDecisionData | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showPreview, setShowPreview] = useState(false)

  useEffect(() => {
    if (data && draft === null) setDraft(structuredClone(data))
  }, [data, draft])

  const ruleErrors = useMemo(() => (draft ? validateRuleIds(draft.rules, copy) : []), [draft, copy])
  const hasErrors = ruleErrors.some(Boolean)

  const dirty = useMemo(() => {
    if (!data || !draft) return false
    const snapshot = (policy: WriteDecisionData) =>
      JSON.stringify({
        enabled: policy.enabled,
        default_action: policy.default_action,
        rules: policy.rules,
      })
    return snapshot(draft) !== snapshot(data)
  }, [data, draft])

  if (isLoading || (!draft && !error)) {
    return (
      <Card className="p-4 md:p-5">
        <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <Loader2 size={15} className="animate-spin" aria-hidden="true" />
          {t.common.loading}
        </div>
      </Card>
    )
  }

  if (error || !draft) {
    return (
      <ErrorAlert
        message={copy.writeDecisionLoadFailed}
        onRetry={() => refetch()}
        retryLabel={t.common.retry}
      />
    )
  }

  const patchRule = (index: number, patch: Partial<WriteDecisionRule>) => {
    setDraft((current) => {
      if (!current) return current
      const rules = current.rules.map((rule, ruleIndex) =>
        ruleIndex === index ? { ...rule, ...patch } : rule,
      )
      return { ...current, rules }
    })
  }

  const patchMatch = (index: number, key: keyof WritePolicyRuleMatch, values: string[]) => {
    setDraft((current) => {
      if (!current) return current
      const rules = current.rules.map((rule, ruleIndex) =>
        ruleIndex === index ? { ...rule, match: { ...rule.match, [key]: values } } : rule,
      )
      return { ...current, rules }
    })
  }

  const changeRuleId = (index: number, id: string) => {
    const previousId = draft.rules[index]?.id
    patchRule(index, { id })
    if (previousId && expandedId === previousId) setExpandedId(id)
  }

  const removeRule = (index: number) => {
    const removedId = draft.rules[index]?.id
    setDraft((current) =>
      current
        ? { ...current, rules: current.rules.filter((_, ruleIndex) => ruleIndex !== index) }
        : current,
    )
    if (removedId && expandedId === removedId) setExpandedId(null)
  }

  const addRule = (action: WriteDecisionAction) => {
    const prefix = action
    let suffix = 1
    while (draft.rules.some((rule) => rule.id === `${prefix}-${suffix}`)) suffix += 1
    const id = `${prefix}-${suffix}`
    setDraft({
      ...draft,
      rules: [
        ...draft.rules,
        {
          id,
          action,
          description: '',
          examples: [],
          match: { workspace: [], type: [], tags: [], keyword: [] },
        },
      ],
    })
    setExpandedId(id)
  }

  const handleReset = () => {
    if (data) setDraft(structuredClone(data))
  }

  const handleSave = () => {
    if (!draft) return
    const rules = [...draft.rules]
      .sort((a, b) => PRIORITY_ORDER.indexOf(a.action) - PRIORITY_ORDER.indexOf(b.action))
      .map((rule) => ({
        ...rule,
        id: rule.id.trim(),
        description: rule.description.trim(),
        examples: rule.examples.map((item) => item.trim()).filter(Boolean),
      }))
    update.mutate(
      { enabled: draft.enabled, default_action: draft.default_action, rules },
      {
        onSuccess: (saved) => {
          setDraft(structuredClone(saved))
          toast(copy.writeDecisionSaveSuccess, 'success')
        },
        onError: (err) => {
          toast(err instanceof Error ? err.message : copy.writeDecisionSaveFailed, 'error')
        },
      },
    )
  }

  const canSave = dirty && !hasErrors && !update.isPending
  const preview = buildPreview(draft, copy)
  const defaultDescription =
    draft.default_action === 'skip'
      ? copy.writeDecisionDefaultSkipDesc
      : copy.writeDecisionDefaultWriteDesc

  const renderGroup = (action: WriteDecisionAction) => {
    const meta = GROUPS[action]
    const entries = draft.rules
      .map((rule, index) => ({ rule, index }))
      .filter((entry) => entry.rule.action === action)

    return (
      <div className={`rounded-xl border p-3 ${meta.panelClass}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h4 className={`text-sm font-semibold ${meta.titleClass}`}>{copy[meta.titleKey]}</h4>
            <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">{copy[meta.descKey]}</p>
          </div>
          <Badge variant={meta.badgeVariant}>{entries.length}</Badge>
        </div>

        <div className="mt-2 space-y-2">
          {entries.length === 0 && (
            <p className="rounded-lg border border-dashed border-[var(--border-default)] bg-surface-card/40 px-3 py-3 text-center text-xs text-[var(--text-tertiary)]">
              {copy.writeDecisionEmptyGroup}
            </p>
          )}
          {entries.map(({ rule, index }) => {
            const expanded = expandedId === rule.id
            return (
              <div
                key={`${rule.id}-${index}`}
                className="group rounded-lg border border-[var(--border-default)] bg-surface-card/70 transition-colors duration-150 hover:border-[var(--border-strong)]"
              >
                <div className="flex items-start gap-2 p-2.5">
                  <button
                    type="button"
                    onClick={() => setExpandedId(expanded ? null : rule.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate text-sm font-medium text-[var(--text-primary)]">
                        {rule.description || copy.writePolicyUntitled}
                      </span>
                      {isEmptyMatch(rule.match) && (
                        <Badge variant="warning">{copy.writePolicyCatchAll}</Badge>
                      )}
                    </div>
                    <p className="mt-0.5 truncate font-mono text-[11px] text-[var(--text-tertiary)]">
                      {rule.id || copy.writePolicyRuleIdPlaceholder}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <MatchChips match={rule.match} copy={copy} />
                    </div>
                  </button>

                  <div className="flex shrink-0 items-center gap-0.5">
                    <div className="transition-opacity duration-150 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                      <Button
                        variant="icon"
                        size="sm"
                        onClick={() => removeRule(index)}
                        aria-label={copy.writePolicyDelete}
                        title={copy.writePolicyDelete}
                      >
                        <Trash2 size={13} aria-hidden="true" />
                      </Button>
                    </div>
                    <Button
                      variant="icon"
                      size="sm"
                      onClick={() => setExpandedId(expanded ? null : rule.id)}
                      aria-expanded={expanded}
                      aria-label={expanded ? copy.writeDecisionCollapse : copy.writeDecisionExpand}
                    >
                      <ChevronDown
                        size={14}
                        className={`transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
                        aria-hidden="true"
                      />
                    </Button>
                  </div>
                </div>

                <AnimatePresence initial={false}>
                  {expanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: duration.normal, ease: ease.out }}
                      className="overflow-hidden"
                    >
                      <div className="border-t border-[var(--border-default)] px-3 pb-3 pt-3">
                        <RuleEditor
                          rule={rule}
                          error={ruleErrors[index]}
                          copy={copy}
                          onChange={(patch) => {
                            if (patch.id !== undefined) changeRuleId(index, patch.id)
                            else patchRule(index, patch)
                          }}
                          onMatchChange={(key, values) => patchMatch(index, key, values)}
                        />
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )
          })}

          <Button variant="secondary" size="sm" onClick={() => addRule(action)}>
            <Plus size={14} aria-hidden="true" />
            {copy[meta.addKey]}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <Card className="p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-2.5">
          <motion.div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-brand-200/25 bg-gradient-to-br from-brand-50 to-brand-100/50 shadow-warm-xs ring-1 ring-brand-200/40"
            whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
            transition={{ duration: duration.modal }}
          >
            <ListChecks size={15} className="text-brand-fg" aria-hidden="true" />
          </motion.div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-[var(--text-primary)]">
              {copy.writeDecision}
            </h3>
            <p className="mt-0.5 text-xs font-medium text-[var(--text-tertiary)]">
              {copy.writeDecisionDesc}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          <Switch
            checked={draft.enabled}
            onCheckedChange={(enabled) => setDraft({ ...draft, enabled })}
          />
          <div>
            <p className="text-xs font-medium text-[var(--text-primary)]">
              {copy.writeDecisionEnabled}
            </p>
            <p className="text-xs text-[var(--text-tertiary)]">{copy.writeDecisionEnabledHint}</p>
          </div>
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-[var(--border-default)] bg-surface-inset/30 px-3 py-2 text-xs font-medium text-[var(--text-secondary)]">
        {copy.writeDecisionFlow}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--text-tertiary)]">
        <span>
          {copy.writePolicyStorage}: <span className="font-mono">{draft.storage_path}</span>
        </span>
        <span aria-hidden="true">·</span>
        <span>{copy.writePolicyStorageHint}</span>
      </div>

      {!draft.enabled && (
        <p className="mt-2 text-xs font-medium text-warning-fg">{copy.writeDecisionDisabledHint}</p>
      )}

      <div className="mt-4 rounded-xl border border-[var(--border-default)] bg-surface-elevated/20 p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-[var(--text-primary)]">
              {copy.writeDecisionDefault}
            </p>
            <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">{defaultDescription}</p>
          </div>
          <SegmentedControl
            value={draft.default_action}
            onChange={(action) => setDraft({ ...draft, default_action: action })}
            options={[
              { value: 'write', label: copy.writeDecisionDefaultWrite },
              { value: 'skip', label: copy.writeDecisionDefaultSkip },
            ]}
          />
        </div>
        {draft.default_action === 'skip' && (
          <p className="mt-2 text-xs font-medium text-warning-fg">
            {copy.writeDecisionDefaultSkipWarning}
          </p>
        )}
      </div>

      <p className="mt-3 text-xs text-[var(--text-tertiary)]">{copy.writeDecisionPriorityHint}</p>

      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        {renderGroup('write')}
        {renderGroup('skip')}
      </div>
      <div className="mt-3">{renderGroup('update')}</div>

      <div className="mt-4">
        <button
          type="button"
          onClick={() => setShowPreview(!showPreview)}
          className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
        >
          <ChevronDown
            size={13}
            className={`transition-transform duration-200 ${showPreview ? 'rotate-180' : ''}`}
            aria-hidden="true"
          />
          {copy.writeDecisionPreview}
        </button>
        <AnimatePresence initial={false}>
          {showPreview && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: duration.normal, ease: ease.out }}
              className="overflow-hidden"
            >
              <div className="mt-2 rounded-xl border border-[var(--border-default)] bg-surface-inset/40 p-3">
                <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-[var(--text-secondary)]">
                  {preview || copy.writeDecisionDisabledHint}
                </pre>
                <p className="mt-2 text-xs text-[var(--text-tertiary)]">
                  {copy.writeDecisionPreviewHint}
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border-default)] pt-4">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-[var(--text-tertiary)]">
            {translate(copy.writePolicyRuleCount, { n: draft.rules.length })}
          </span>
          {dirty && <span className="font-medium text-warning-fg">{copy.writePolicyUnsaved}</span>}
        </div>
        <div className="flex items-center gap-2">
          {dirty && (
            <Button variant="ghost" size="sm" onClick={handleReset} disabled={update.isPending}>
              <RotateCcw size={13} aria-hidden="true" />
              {copy.writePolicyReset}
            </Button>
          )}
          <Button size="sm" onClick={handleSave} disabled={!canSave}>
            {update.isPending ? (
              <Loader2 size={13} className="animate-spin" aria-hidden="true" />
            ) : (
              <Save size={13} aria-hidden="true" />
            )}
            {update.isPending ? copy.writeDecisionSaving : copy.writeDecisionSave}
          </Button>
        </div>
      </div>
    </Card>
  )
}
