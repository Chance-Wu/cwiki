import { useEffect, useId, useRef, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { twMerge } from 'tailwind-merge'
import { AlertTriangle } from 'lucide-react'
import type { WritePolicyRuleMatch } from '../../lib/api'
import { Badge } from '../ui/Badge'
import { Textarea } from '../ui/Textarea'
import { isEmptyMatch } from './writeRuleUtils'

const CHIP_PREVIEW_LIMIT = 3

function parseListInput(raw: string): string[] {
  const seen = new Set<string>()
  return raw
    .split(/[,，\n]/)
    .map((part) => part.trim())
    .filter((part) => {
      if (!part) return false
      const key = part.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

export interface MatchFieldLimits {
  workspace: number
  type: number
  tags: number
  keyword: number
  regex: number
  valueChars: number
}

export function ListInput({
  label,
  value,
  onChange,
  placeholder,
  hint,
  max,
  maxValueLength = 100,
  invalid = false,
  removeLabel,
}: {
  label: string
  value: string[]
  onChange: (values: string[]) => void
  placeholder: string
  hint: string
  max?: number
  maxValueLength?: number
  invalid?: boolean
  removeLabel?: string
}) {
  const inputId = useId()
  const hintId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')

  const commit = (raw: string) => {
    const next = [...value]
    const seen = new Set(next.map((item) => item.toLowerCase()))
    for (const part of parseListInput(raw)) {
      const text = part.slice(0, maxValueLength)
      const key = text.toLowerCase()
      if (seen.has(key)) continue
      if (max !== undefined && next.length >= max) break
      seen.add(key)
      next.push(text)
    }
    if (next.length !== value.length) onChange(next)
  }

  const atLimit = max !== undefined && value.length >= max

  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={inputId} className="block text-xs font-medium text-[var(--text-secondary)]">
          {label}
        </label>
        {max !== undefined && (
          <span
            className={twMerge(
              'shrink-0 text-xs tabular-nums',
              atLimit ? 'font-medium text-warning-fg' : 'text-[var(--text-tertiary)]',
            )}
          >
            {value.length}/{max}
          </span>
        )}
      </div>

      <div
        className={twMerge(
          'mt-1.5 flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg border px-2 py-1.5',
          'bg-surface-card shadow-warm-xs backdrop-blur-[var(--glass-blur)]',
          'transition-[border-color,box-shadow] duration-200 ease-out',
          invalid
            ? 'border-danger/60 focus-within:ring-2 focus-within:ring-danger/20'
            : 'border-[var(--glass-border)] focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-200/30',
        )}
        onClick={() => inputRef.current?.focus()}
      >
        <AnimatePresence initial={false}>
          {value.map((item) => (
            <Badge
              key={item}
              variant="default"
              removable
              onRemove={() => onChange(value.filter((entry) => entry !== item))}
              removeLabel={removeLabel ? `${removeLabel}: ${item}` : undefined}
              className="max-w-full"
            >
              <span className="truncate" title={item}>
                {item}
              </span>
            </Badge>
          ))}
        </AnimatePresence>
        <input
          id={inputId}
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ',' || event.key === '，') {
              event.preventDefault()
              commit(query)
              setQuery('')
            } else if (event.key === 'Backspace' && query === '' && value.length > 0) {
              onChange(value.slice(0, -1))
            }
          }}
          onPaste={(event) => {
            const text = event.clipboardData.getData('text')
            if (!/[,，\n]/.test(text)) return
            event.preventDefault()
            commit(query + text)
            setQuery('')
          }}
          onBlur={() => {
            commit(query)
            setQuery('')
          }}
          placeholder={value.length === 0 ? placeholder : ''}
          aria-describedby={hintId}
          className="min-w-[6rem] flex-1 bg-transparent px-1 py-0.5 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
        />
      </div>
      <p id={hintId} className="mt-1 text-xs text-[var(--text-tertiary)]">
        {hint}
      </p>
    </div>
  )
}

export function LinesInput({
  label,
  value,
  onChange,
  placeholder,
  hint,
  max = 5,
  maxLength = 120,
  overLimitMessage,
}: {
  label: string
  value: string[]
  onChange: (values: string[]) => void
  placeholder: string
  hint: string
  max?: number
  maxLength?: number
  overLimitMessage?: string
}) {
  const inputId = useId()
  const [text, setText] = useState(value.join('\n'))
  const lastEmitted = useRef(value)
  const overLimit = value.some((item) => item.length > maxLength)

  useEffect(() => {
    // 只在外部值变化（撤销草稿）时同步，避免覆盖输入中的换行
    if (value !== lastEmitted.current) {
      lastEmitted.current = value
      setText(value.join('\n'))
    }
  }, [value])

  const emit = (raw: string) => {
    const next = raw
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, max)
    lastEmitted.current = next
    onChange(next)
  }

  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={inputId} className="block text-xs font-medium text-[var(--text-secondary)]">
          {label}
        </label>
        <span className="shrink-0 text-xs tabular-nums text-[var(--text-tertiary)]">
          {value.length}/{max}
        </span>
      </div>
      <Textarea
        id={inputId}
        value={text}
        onChange={(event) => {
          setText(event.target.value)
          emit(event.target.value)
        }}
        onBlur={() => {
          emit(text)
          setText(
            text
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean)
              .slice(0, max)
              .join('\n'),
          )
        }}
        placeholder={placeholder}
        rows={3}
        className="mt-1.5"
      />
      <p className="mt-1 text-xs text-[var(--text-tertiary)]">{hint}</p>
      {overLimit && overLimitMessage && (
        <p className="mt-1 flex items-center gap-1 text-xs font-medium text-danger-fg">
          <AlertTriangle size={12} aria-hidden="true" />
          {overLimitMessage}
        </p>
      )}
    </div>
  )
}

export function MatchChips({
  match,
  copy,
}: {
  match: WritePolicyRuleMatch
  copy: Record<string, string>
}) {
  const chips = [
    { label: copy.writePolicyWorkspace, values: match.workspace },
    { label: copy.writePolicyType, values: match.type },
    { label: copy.writePolicyTags, values: match.tags },
    { label: copy.writePolicyKeyword, values: match.keyword },
    { label: copy.writePolicyRegex, values: match.regex },
  ].filter((chip) => chip.values.length > 0)

  if (chips.length === 0) {
    return <span className="text-xs text-[var(--text-tertiary)]">{copy.writePolicyNoMatch}</span>
  }

  return (
    <>
      {chips.map((chip) => {
        const shown = chip.values.slice(0, CHIP_PREVIEW_LIMIT)
        const hidden = chip.values.length - shown.length
        return (
          <Badge key={chip.label} variant="default" className="max-w-full">
            <span className="whitespace-nowrap text-[var(--text-tertiary)]">{chip.label}</span>
            <span className="truncate">
              {shown.join(', ')}
              {hidden > 0 ? ` +${hidden}` : ''}
            </span>
          </Badge>
        )
      })}
    </>
  )
}

export function MatchEditor({
  match,
  onMatchChange,
  hint,
  warning,
  copy,
  limits,
}: {
  match: WritePolicyRuleMatch
  onMatchChange: (key: keyof WritePolicyRuleMatch, values: string[]) => void
  hint: string
  warning: string
  copy: Record<string, string>
  limits?: MatchFieldLimits
}) {
  const fieldLimits = limits ?? {
    workspace: 20,
    type: 20,
    tags: 20,
    keyword: 30,
    regex: 20,
    valueChars: 100,
  }

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs font-medium text-[var(--text-secondary)]">{copy.writePolicyMatch}</p>
        <p className="text-xs text-[var(--text-tertiary)]">{hint}</p>
      </div>
      <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-4">
        <ListInput
          label={copy.writePolicyWorkspace}
          value={match.workspace}
          onChange={(values) => onMatchChange('workspace', values)}
          placeholder="cwiki"
          hint={copy.writePolicyWorkspaceHint}
          removeLabel={copy.writePolicyRemoveValue}
          max={fieldLimits.workspace}
          maxValueLength={fieldLimits.valueChars}
        />
        <ListInput
          label={copy.writePolicyType}
          value={match.type}
          onChange={(values) => onMatchChange('type', values)}
          placeholder="decision, lesson"
          hint={copy.writePolicyTypeHint}
          removeLabel={copy.writePolicyRemoveValue}
          max={fieldLimits.type}
          maxValueLength={fieldLimits.valueChars}
        />
        <ListInput
          label={copy.writePolicyTags}
          value={match.tags}
          onChange={(values) => onMatchChange('tags', values)}
          placeholder="pinned"
          hint={copy.writePolicyTagsHint}
          removeLabel={copy.writePolicyRemoveValue}
          max={fieldLimits.tags}
          maxValueLength={fieldLimits.valueChars}
        />
        <ListInput
          label={copy.writePolicyKeyword}
          value={match.keyword}
          onChange={(values) => onMatchChange('keyword', values)}
          placeholder="必须保留, ECONNRESET"
          hint={copy.writePolicyKeywordHint}
          removeLabel={copy.writePolicyRemoveValue}
          max={fieldLimits.keyword}
          maxValueLength={fieldLimits.valueChars}
        />
        <ListInput
          label={copy.writePolicyRegex}
          value={match.regex}
          onChange={(values) => onMatchChange('regex', values)}
          placeholder={String.raw`(?i)password\s*[=:]\s*\S+`}
          hint={copy.writePolicyRegexHint}
          removeLabel={copy.writePolicyRemoveValue}
          max={fieldLimits.regex}
          maxValueLength={fieldLimits.valueChars}
        />
      </div>
      {isEmptyMatch(match) && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning-fg">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{warning}</span>
        </div>
      )}
    </div>
  )
}
