import { useEffect, useId, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Copy,
  ListFilter,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Trash2,
} from 'lucide-react'
import { duration, ease } from '../../lib/motion'
import { translate, useTranslation } from '../../i18n/I18nProvider'
import type {
  WritePolicyAction,
  WritePolicyData,
  WritePolicyRule,
  WritePolicyRuleMatch,
} from '../../lib/api'
import type { WritePolicyLimits } from '../../lib/api/types'
import { useWritePolicy } from '../../hooks/useSettings'
import { useBeforeUnloadGuard } from '../../hooks/useBeforeUnload'
import ErrorAlert from '../ErrorAlert'
import { useToast } from '../Toast'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Input } from '../ui/Input'
import { SegmentedControl } from '../ui/SegmentedControl'
import { Switch } from '../ui/Switch'
import { MatchChips, MatchEditor } from './writeRuleShared'
import {
  DEFAULT_WRITE_POLICY_LIMITS,
  collectWritePolicyLimitIssues,
  isEmptyMatch,
  validateRuleIds,
} from './writeRuleUtils'

const ACTION_VARIANTS: Record<WritePolicyAction, 'success' | 'warning' | 'danger'> = {
  auto: 'success',
  review: 'warning',
  reject: 'danger',
}

const ACTION_LABEL_KEYS: Record<WritePolicyAction, string> = {
  auto: 'writePolicyActionAuto',
  review: 'writePolicyActionReview',
  reject: 'writePolicyActionReject',
}

const ACTION_DESC_KEYS: Record<WritePolicyAction, string> = {
  auto: 'writePolicyActionAutoDesc',
  review: 'writePolicyActionReviewDesc',
  reject: 'writePolicyActionRejectDesc',
}

function RuleEditor({
  rule,
  error,
  copy,
  limits,
  onChange,
  onMatchChange,
}: {
  rule: WritePolicyRule
  error: string | null
  copy: Record<string, string>
  limits: WritePolicyLimits
  onChange: (patch: Partial<WritePolicyRule>) => void
  onMatchChange: (key: keyof WritePolicyRuleMatch, values: string[]) => void
}) {
  const idInputId = useId()
  const reasonInputId = useId()

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
          <p className="text-xs font-medium text-[var(--text-secondary)]">
            {copy.writePolicyAction}
          </p>
          <div className="mt-1.5" role="group" aria-label={copy.writePolicyAction}>
            <SegmentedControl
              value={rule.action}
              onChange={(action) => onChange({ action })}
              options={[
                { value: 'auto', label: copy.writePolicyActionAuto },
                { value: 'review', label: copy.writePolicyActionReview },
                { value: 'reject', label: copy.writePolicyActionReject },
              ]}
            />
          </div>
          <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
            {copy[ACTION_DESC_KEYS[rule.action]]}
          </p>
        </div>
      </div>

      <div>
        <label
          htmlFor={reasonInputId}
          className="block text-xs font-medium text-[var(--text-secondary)]"
        >
          {copy.writePolicyReason}
        </label>
        <Input
          id={reasonInputId}
          value={rule.reason ?? ''}
          onChange={(event) => onChange({ reason: event.target.value || null })}
          placeholder={copy.writePolicyReasonPlaceholder}
          className="mt-1.5"
        />
      </div>

      <MatchEditor
        match={rule.match}
        onMatchChange={onMatchChange}
        hint={copy.writePolicyMatchHint}
        warning={copy.writePolicyCatchAllWarning}
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

export default function WritePolicyCard() {
  const { t } = useTranslation()
  const copy = t.config as Record<string, string>
  const { toast } = useToast()
  const { data, isLoading, error, refetch, update } = useWritePolicy()

  const [draft, setDraft] = useState<WritePolicyData | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    if (data && draft === null) setDraft(structuredClone(data))
  }, [data, draft])

  const limits = data?.limits ?? DEFAULT_WRITE_POLICY_LIMITS
  const ruleErrors = useMemo(() => (draft ? validateRuleIds(draft.rules, copy) : []), [draft, copy])
  const limitIssues = useMemo(
    () => (draft ? collectWritePolicyLimitIssues(draft.rules, copy, limits) : []),
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

  const hasErrors = summaryIssues.length > 0 || (draft?.rules.length ?? 0) > limits.max_rules

  const dirty = useMemo(() => {
    if (!data || !draft) return false
    const snapshot = (policy: WritePolicyData) =>
      JSON.stringify({ enabled: policy.enabled, rules: policy.rules })
    return snapshot(draft) !== snapshot(data)
  }, [data, draft])

  useBeforeUnloadGuard(dirty)

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
        message={copy.writePolicyLoadFailed}
        onRetry={() => refetch()}
        retryLabel={t.common.retry}
      />
    )
  }

  const patchRule = (index: number, patch: Partial<WritePolicyRule>) => {
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

  const moveRule = (index: number, delta: number) => {
    setDraft((current) => {
      if (!current) return current
      const target = index + delta
      if (target < 0 || target >= current.rules.length) return current
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

  const duplicateRule = (index: number) => {
    if (draft.rules.length >= limits.max_rules) {
      toast(translate(copy.writePolicyRuleLimit, { max: limits.max_rules }), 'warning')
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
    const cloned = structuredClone({ ...original, id })
    setDraft((current) => {
      if (!current) return current
      const rules = [...current.rules]
      rules.splice(index + 1, 0, cloned)
      return { ...current, rules }
    })
    setExpandedId(id)
  }

  const addRule = () => {
    let suffix = draft.rules.length + 1
    while (draft.rules.some((rule) => rule.id === `rule-${suffix}`)) suffix += 1
    const id = `rule-${suffix}`
    setDraft({
      ...draft,
      rules: [
        ...draft.rules,
        {
          id,
          action: 'review',
          reason: null,
          match: { workspace: [], type: [], tags: [], keyword: [], regex: [] },
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
    const rules = draft.rules.map((rule) => ({
      ...rule,
      id: rule.id.trim(),
      reason: rule.reason?.trim() || null,
    }))
    update.mutate(
      { enabled: draft.enabled, rules },
      {
        onSuccess: (saved) => {
          setDraft(structuredClone(saved))
          toast(copy.writePolicySaveSuccess, 'success')
        },
        onError: (err) => {
          toast(err instanceof Error ? err.message : copy.writePolicySaveFailed, 'error')
        },
      },
    )
  }

  const canSave = dirty && !hasErrors && !update.isPending

  return (
    <Card className="p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-2.5">
          <motion.div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-brand-200/25 bg-gradient-to-br from-brand-50 to-brand-100/50 shadow-warm-xs ring-1 ring-brand-200/40"
            whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
            transition={{ duration: duration.modal }}
          >
            <ListFilter size={15} className="text-brand-fg" aria-hidden="true" />
          </motion.div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-[var(--text-primary)]">
              {copy.writePolicy}
            </h3>
            <p className="mt-0.5 text-xs font-medium text-[var(--text-tertiary)]">
              {copy.writePolicyDesc}
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
              {copy.writePolicyEnabled}
            </p>
            <p className="text-xs text-[var(--text-tertiary)]">{copy.writePolicyEnabledHint}</p>
          </div>
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
        <p className="mt-2 text-xs font-medium text-warning-fg">{copy.writePolicyDisabledHint}</p>
      )}

      <p className="mt-3 text-xs text-[var(--text-tertiary)]">{copy.writePolicyOrderHint}</p>

      <div className="mt-4 space-y-2.5">
        {draft.rules.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border-default)] bg-surface-elevated/10 px-4 py-6 text-center">
            <p className="text-sm font-medium text-[var(--text-secondary)]">
              {copy.writePolicyEmpty}
            </p>
            <p className="mt-1 text-xs text-[var(--text-tertiary)]">{copy.writePolicyEmptyHint}</p>
          </div>
        ) : (
          draft.rules.map((rule, index) => {
            const expanded = expandedId === rule.id
            return (
              <div
                key={`${rule.id}-${index}`}
                className="group rounded-xl border border-[var(--border-default)] bg-surface-elevated/20 transition-colors duration-150 hover:border-[var(--border-strong)]"
              >
                <div className="flex items-start gap-3 p-3">
                  <button
                    type="button"
                    onClick={() => setExpandedId(expanded ? null : rule.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="w-4 text-right text-[11px] tabular-nums text-[var(--text-tertiary)]">
                        {index + 1}
                      </span>
                      <span className="truncate font-mono text-sm font-semibold text-[var(--text-primary)]">
                        {rule.id || copy.writePolicyUntitled}
                      </span>
                      <Badge variant={ACTION_VARIANTS[rule.action]}>
                        {copy[ACTION_LABEL_KEYS[rule.action]]}
                      </Badge>
                      {isEmptyMatch(rule.match) && (
                        <Badge variant="warning">{copy.writePolicyCatchAll}</Badge>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-6">
                      <MatchChips match={rule.match} copy={copy} />
                    </div>
                    {rule.reason && (
                      <p className="mt-1 truncate pl-6 text-xs text-[var(--text-tertiary)]">
                        {rule.reason}
                      </p>
                    )}
                  </button>

                  <div className="flex shrink-0 items-center gap-0.5">
                    <div className="flex items-center gap-0.5 transition-opacity duration-150 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                      <Button
                        variant="icon"
                        size="sm"
                        onClick={() => moveRule(index, -1)}
                        disabled={index === 0}
                        aria-label={copy.writePolicyMoveUp}
                        title={copy.writePolicyMoveUp}
                      >
                        <ArrowUp size={13} aria-hidden="true" />
                      </Button>
                      <Button
                        variant="icon"
                        size="sm"
                        onClick={() => moveRule(index, 1)}
                        disabled={index === draft.rules.length - 1}
                        aria-label={copy.writePolicyMoveDown}
                        title={copy.writePolicyMoveDown}
                      >
                        <ArrowDown size={13} aria-hidden="true" />
                      </Button>
                      <Button
                        variant="icon"
                        size="sm"
                        onClick={() => duplicateRule(index)}
                        disabled={draft.rules.length >= limits.max_rules}
                        aria-label={copy.writePolicyDuplicate}
                        title={copy.writePolicyDuplicate}
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
                      aria-label={expanded ? copy.writePolicyCollapse : copy.writePolicyExpand}
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
          })
        )}

        <Button
          variant="secondary"
          size="sm"
          onClick={addRule}
          disabled={draft.rules.length >= limits.max_rules}
        >
          <Plus size={14} aria-hidden="true" />
          {copy.writePolicyAddRule}
        </Button>
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
            {translate(copy.writePolicyRuleCount, { n: draft.rules.length, max: limits.max_rules })}
            {draft.rules.length > limits.max_rules && (
              <span className="ml-1 font-medium text-danger-fg">
                ({translate(copy.writePolicyRuleCountExceed, { max: limits.max_rules })})
              </span>
            )}
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
            {update.isPending ? copy.writePolicySaving : copy.writePolicySave}
          </Button>
        </div>
      </div>
    </Card>
  )
}
