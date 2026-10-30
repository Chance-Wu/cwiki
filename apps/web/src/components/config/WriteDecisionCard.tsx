import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Copy,
  ListChecks,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Trash2,
} from 'lucide-react'
import { duration, ease } from '../../lib/motion'
import { translate, useTranslation } from '../../i18n/I18nProvider'
import type {
  WriteDecisionAction,
  WriteDecisionData,
  WriteDecisionLimits,
  WriteDecisionPreview,
  WriteDecisionRule,
  WritePolicyRuleMatch,
} from '../../lib/api'
import { useWriteDecision, useWriteDecisionPreview } from '../../hooks/useSettings'
import { useBeforeUnloadGuard } from '../../hooks/useBeforeUnload'
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
import {
  DEFAULT_WRITE_DECISION_LIMITS,
  collectLimitIssues,
  isEmptyMatch,
  validateRuleIds,
} from './writeRuleUtils'

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

function normalizeRules(rules: WriteDecisionRule[]): WriteDecisionRule[] {
  return rules.map((rule) => ({
    ...rule,
    id: rule.id.trim(),
    description: rule.description.trim(),
    examples: rule.examples.map((item) => item.trim()).filter(Boolean),
  }))
}

function RuleEditor({
  rule,
  error,
  copy,
  limits,
  onChange,
  onMatchChange,
}: {
  rule: WriteDecisionRule
  error: string | null
  copy: Record<string, string>
  limits: WriteDecisionLimits
  onChange: (patch: Partial<WriteDecisionRule>) => void
  onMatchChange: (key: keyof WritePolicyRuleMatch, values: string[]) => void
}) {
  const idInputId = useId()
  const descriptionId = useId()
  const descriptionOver = rule.description.length > limits.max_description

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
        <div className="flex items-baseline justify-between gap-2">
          <label
            htmlFor={descriptionId}
            className="block text-xs font-medium text-[var(--text-secondary)]"
          >
            {copy.writeDecisionDescription}
          </label>
          <span
            className={`shrink-0 text-xs tabular-nums ${
              descriptionOver ? 'font-medium text-danger-fg' : 'text-[var(--text-tertiary)]'
            }`}
          >
            {rule.description.length}/{limits.max_description}
          </span>
        </div>
        <Textarea
          id={descriptionId}
          value={rule.description}
          onChange={(event) => onChange({ description: event.target.value })}
          placeholder={copy.writeDecisionDescriptionPlaceholder}
          rows={2}
          className="mt-1.5"
          aria-invalid={descriptionOver}
        />
      </div>

      <LinesInput
        label={copy.writeDecisionExamples}
        value={rule.examples}
        onChange={(values) => onChange({ examples: values })}
        placeholder={copy.writeDecisionExamplesPlaceholder}
        hint={translate(copy.writeDecisionExamplesHint, { max: limits.max_examples })}
        max={limits.max_examples}
        maxLength={limits.max_example_chars}
        overLimitMessage={translate(copy.writeDecisionIssueExampleLength, {
          max: limits.max_example_chars,
        })}
      />

      <MatchEditor
        match={rule.match}
        onMatchChange={onMatchChange}
        hint={copy.writePolicyMatchHint}
        warning={copy.writeDecisionCatchAllWarning}
        copy={copy}
        limits={{
          workspace: limits.max_match_values,
          type: limits.max_match_values,
          tags: limits.max_match_values,
          keyword: limits.max_keyword_values,
          regex: limits.max_regex_values,
          valueChars: limits.max_match_value_chars,
        }}
      />
    </div>
  )
}

export default function WriteDecisionCard() {
  const { t } = useTranslation()
  const copy = t.config as Record<string, string>
  const { toast } = useToast()
  const { data, isLoading, error, refetch, update } = useWriteDecision()
  const { mutate: runPreview, isPending: previewPending } = useWriteDecisionPreview()

  const [draft, setDraft] = useState<WriteDecisionData | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showPreview, setShowPreview] = useState(false)
  const [previewWorkspace, setPreviewWorkspace] = useState('')
  const [previewResult, setPreviewResult] = useState<WriteDecisionPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const previewSeq = useRef(0)

  useEffect(() => {
    if (data && draft === null) setDraft(structuredClone(data))
  }, [data, draft])

  const limits = data?.limits ?? DEFAULT_WRITE_DECISION_LIMITS
  const ruleErrors = useMemo(() => (draft ? validateRuleIds(draft.rules, copy) : []), [draft, copy])
  const limitIssues = useMemo(
    () => (draft ? collectLimitIssues(draft.rules, copy, limits) : []),
    [draft, copy, limits],
  )

  const summaryIssues = useMemo(() => {
    if (!draft) return []
    return draft.rules
      .map((rule, index) => {
        const messages: string[] = []
        if (ruleErrors[index]) messages.push(ruleErrors[index] as string)
        const limit = limitIssues.find((issue) => issue.index === index)
        if (limit) messages.push(...limit.messages)
        if (messages.length === 0) return null
        return {
          index,
          ruleId: rule.id.trim() || copy.writePolicyUntitled,
          messages,
        }
      })
      .filter((entry): entry is { index: number; ruleId: string; messages: string[] } =>
        Boolean(entry),
      )
  }, [draft, ruleErrors, limitIssues, copy.writePolicyUntitled])

  const hasErrors = summaryIssues.length > 0

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

  useBeforeUnloadGuard(dirty)

  const counts = useMemo(() => {
    const total: Record<WriteDecisionAction, number> = { write: 0, skip: 0, update: 0 }
    draft?.rules.forEach((rule) => {
      total[rule.action] += 1
    })
    return total
  }, [draft])

  // 打开预览后按草稿实时生成；输入停顿 350ms 再请求，避免每个按键都打服务端
  useEffect(() => {
    if (!showPreview || !draft) return
    const seq = previewSeq.current + 1
    previewSeq.current = seq
    const timer = setTimeout(() => {
      runPreview(
        {
          enabled: draft.enabled,
          default_action: draft.default_action,
          rules: normalizeRules(draft.rules),
          workspace: previewWorkspace.trim(),
        },
        {
          onSuccess: (result) => {
            if (seq !== previewSeq.current) return
            setPreviewResult(result)
            setPreviewError(null)
          },
          onError: (err) => {
            if (seq !== previewSeq.current) return
            setPreviewError(err instanceof Error ? err.message : copy.writeDecisionPreviewError)
          },
        },
      )
    }, 350)
    return () => {
      clearTimeout(timer)
      // 草稿继续变化时让在途响应失效，避免旧预览覆盖新结果
      previewSeq.current += 1
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showPreview, draft, previewWorkspace, runPreview])

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

  const moveRuleWithinGroup = (index: number, delta: number) => {
    setDraft((current) => {
      if (!current) return current
      const action = current.rules[index]?.action
      if (!action) return current
      const groupIndices = current.rules
        .map((rule, ruleIndex) => (rule.action === action ? ruleIndex : -1))
        .filter((ruleIndex) => ruleIndex >= 0)
      const position = groupIndices.indexOf(index)
      const target = groupIndices[position + delta]
      if (position < 0 || target === undefined) return current
      const rules = [...current.rules]
      ;[rules[index], rules[target]] = [rules[target], rules[index]]
      return { ...current, rules }
    })
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

  const atRuleLimit = draft.rules.length >= limits.max_rules

  const addRule = (action: WriteDecisionAction) => {
    if (atRuleLimit) return
    let suffix = 1
    while (draft.rules.some((rule) => rule.id === `${action}-${suffix}`)) suffix += 1
    const id = `${action}-${suffix}`
    setDraft({
      ...draft,
      rules: [
        ...draft.rules,
        {
          id,
          action,
          description: '',
          examples: [],
          match: { workspace: [], type: [], tags: [], keyword: [], regex: [] },
        },
      ],
    })
    setExpandedId(id)
  }

  const duplicateRule = (index: number) => {
    if (atRuleLimit) {
      toast(translate(copy.writeDecisionRuleLimit, { max: limits.max_rules }), 'warning')
      return
    }
    const original = draft.rules[index]
    if (!original) return
    const seed = (original.id.trim() || original.action).replace(/[^A-Za-z0-9._-]+/g, '-')
    const base = `${seed}-copy`
    let id = base
    let suffix = 1
    while (draft.rules.some((rule) => rule.id === id)) {
      suffix += 1
      id = `${base}-${suffix}`
    }
    const copyRule = structuredClone({ ...original, id })
    const rules = [...draft.rules]
    rules.splice(index + 1, 0, copyRule)
    setDraft({ ...draft, rules })
    setExpandedId(id)
  }

  const handleReset = () => {
    if (data) {
      setDraft(structuredClone(data))
      setPreviewError(null)
    }
  }

  const handleSave = () => {
    if (!draft) return
    const rules = [...draft.rules]
      .sort((a, b) => PRIORITY_ORDER.indexOf(a.action) - PRIORITY_ORDER.indexOf(b.action))
      .map((rule) => normalizeRules([rule])[0])
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
  const defaultDescription =
    draft.default_action === 'skip'
      ? copy.writeDecisionDefaultSkipDesc
      : copy.writeDecisionDefaultWriteDesc

  const previewBudget = previewResult
    ? Math.min(100, Math.round((previewResult.length / Math.max(1, previewResult.max_chars)) * 100))
    : 0
  const budgetBarClass =
    previewBudget >= 90 ? 'bg-danger' : previewBudget >= 75 ? 'bg-warning' : 'bg-brand-500'

  const renderGroup = (action: WriteDecisionAction, priority: number) => {
    const meta = GROUPS[action]
    const entries = draft.rules
      .map((rule, index) => ({ rule, index }))
      .filter((entry) => entry.rule.action === action)

    return (
      <div className={`rounded-xl border p-3 ${meta.panelClass}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-start gap-2">
            <span
              title={translate(copy.writeDecisionGroupPriority, { n: priority })}
              className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border border-current/25 text-[11px] font-semibold tabular-nums opacity-80 ${meta.titleClass}`}
            >
              {priority}
            </span>
            <div className="min-w-0">
              <h4 className={`text-sm font-semibold ${meta.titleClass}`}>{copy[meta.titleKey]}</h4>
              <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">{copy[meta.descKey]}</p>
            </div>
          </div>
          <Badge variant={meta.badgeVariant}>{entries.length}</Badge>
        </div>

        <div className="mt-2 space-y-2">
          {entries.length === 0 && (
            <p className="rounded-lg border border-dashed border-[var(--border-default)] bg-surface-card/40 px-3 py-3 text-center text-xs text-[var(--text-tertiary)]">
              {copy.writeDecisionEmptyGroup}
            </p>
          )}
          {entries.map(({ rule, index }, position) => {
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
                    <div className="flex items-center gap-0.5 transition-opacity duration-150 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                      <Button
                        variant="icon"
                        size="sm"
                        onClick={() => moveRuleWithinGroup(index, -1)}
                        disabled={position === 0}
                        aria-label={copy.writePolicyMoveUp}
                        title={copy.writePolicyMoveUp}
                      >
                        <ArrowUp size={13} aria-hidden="true" />
                      </Button>
                      <Button
                        variant="icon"
                        size="sm"
                        onClick={() => moveRuleWithinGroup(index, 1)}
                        disabled={position === entries.length - 1}
                        aria-label={copy.writePolicyMoveDown}
                        title={copy.writePolicyMoveDown}
                      >
                        <ArrowDown size={13} aria-hidden="true" />
                      </Button>
                      <Button
                        variant="icon"
                        size="sm"
                        onClick={() => duplicateRule(index)}
                        disabled={atRuleLimit}
                        aria-label={copy.writeDecisionDuplicate}
                        title={copy.writeDecisionDuplicate}
                      >
                        <Copy size={13} aria-hidden="true" />
                      </Button>
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
                          limits={limits}
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

          <Button
            variant="secondary"
            size="sm"
            onClick={() => addRule(action)}
            disabled={atRuleLimit}
            title={
              atRuleLimit
                ? translate(copy.writeDecisionRuleLimit, { max: limits.max_rules })
                : undefined
            }
          >
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

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-[var(--border-default)] bg-surface-inset/30 px-3 py-2">
        <span className="text-xs font-medium text-[var(--text-secondary)]">
          {copy.writeDecisionFlow}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <Badge variant="danger">
            {counts.skip} {copy.writeDecisionActionSkip}
          </Badge>
          <Badge variant="info">
            {counts.update} {copy.writeDecisionActionUpdate}
          </Badge>
          <Badge variant="success">
            {counts.write} {copy.writeDecisionActionWrite}
          </Badge>
        </div>
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

      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
        {renderGroup('skip', 1)}
        {renderGroup('update', 2)}
      </div>
      <div className="mt-3">{renderGroup('write', 3)}</div>

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
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-[var(--text-tertiary)]">
                    {copy.writeDecisionPreviewWorkspace}
                  </span>
                  <Input
                    value={previewWorkspace}
                    onChange={(event) => setPreviewWorkspace(event.target.value)}
                    placeholder={copy.writeDecisionPreviewWorkspacePlaceholder}
                    className="h-8 w-44 py-1 text-xs"
                  />
                  {previewPending && (
                    <span className="flex items-center gap-1 text-xs text-[var(--text-tertiary)]">
                      <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                      {copy.writeDecisionPreviewLoading}
                    </span>
                  )}
                  {previewResult && !previewPending && (
                    <span className="ml-auto text-xs tabular-nums text-[var(--text-tertiary)]">
                      {translate(copy.writeDecisionPreviewRules, {
                        shown: previewResult.shown_rules,
                        total: previewResult.total_rules,
                      })}
                    </span>
                  )}
                </div>

                {previewResult && (
                  <div className="mt-2">
                    <div className="flex items-baseline justify-between text-xs">
                      <span className="text-[var(--text-tertiary)]">
                        {translate(copy.writeDecisionPreviewBudget, {
                          used: previewResult.length,
                          max: previewResult.max_chars,
                        })}
                      </span>
                      <span className="tabular-nums text-[var(--text-tertiary)]">
                        {previewBudget}%
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-elevated">
                      <div
                        className={`h-full rounded-full transition-[width] duration-300 ease-out ${budgetBarClass}`}
                        style={{ width: `${previewBudget}%` }}
                      />
                    </div>
                  </div>
                )}

                {previewResult?.truncated && (
                  <p className="mt-2 flex items-start gap-1.5 text-xs font-medium text-warning-fg">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {translate(copy.writeDecisionPreviewTruncated, {
                      n: previewResult.total_rules - previewResult.shown_rules,
                    })}
                  </p>
                )}
                {previewResult && previewResult.skipped_rules > 0 && (
                  <p className="mt-2 flex items-start gap-1.5 text-xs font-medium text-warning-fg">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {translate(copy.writeDecisionPreviewSkipped, {
                      n: previewResult.skipped_rules,
                    })}
                  </p>
                )}
                {previewError && (
                  <p className="mt-2 text-xs font-medium text-danger-fg">{previewError}</p>
                )}

                <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-[var(--text-secondary)]">
                  {previewResult?.preview ||
                    (previewPending
                      ? copy.writeDecisionPreviewLoading
                      : copy.writeDecisionPreviewEmpty)}
                </pre>
                <p className="mt-2 text-xs text-[var(--text-tertiary)]">
                  {copy.writeDecisionPreviewHint}
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {summaryIssues.length > 0 && (
        <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger-fg">
          <p className="font-medium">
            {translate(copy.writeDecisionIssueSummary, { n: summaryIssues.length })}
          </p>
          <ul className="mt-1 space-y-0.5">
            {summaryIssues.slice(0, 3).map((issue) => (
              <li key={`${issue.index}-${issue.ruleId}`}>
                <span className="font-mono">{issue.ruleId}</span>：{issue.messages.join('；')}
              </li>
            ))}
            {summaryIssues.length > 3 && <li>…</li>}
          </ul>
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border-default)] pt-4">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-[var(--text-tertiary)]">
            {translate(copy.writeDecisionRuleCount, {
              n: draft.rules.length,
              max: limits.max_rules,
            })}
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
