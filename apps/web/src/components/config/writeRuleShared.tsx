import { useEffect, useId, useRef, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import type { WritePolicyRuleMatch } from '../../lib/api'
import { Badge } from '../ui/Badge'
import { Input } from '../ui/Input'
import { Textarea } from '../ui/Textarea'
import { isEmptyMatch } from './writeRuleUtils'

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

export function ListInput({
  label,
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string
  value: string[]
  onChange: (values: string[]) => void
  placeholder: string
  hint: string
}) {
  const inputId = useId()
  const [text, setText] = useState(value.join(', '))
  const lastEmitted = useRef(value)

  useEffect(() => {
    // 只在外部值变化（例如重置草稿）时同步，避免覆盖输入中的逗号与空格
    if (value !== lastEmitted.current) {
      lastEmitted.current = value
      setText(value.join(', '))
    }
  }, [value])

  const emit = (raw: string) => {
    const next = parseListInput(raw)
    lastEmitted.current = next
    onChange(next)
  }

  return (
    <div className="min-w-0">
      <label htmlFor={inputId} className="block text-xs font-medium text-[var(--text-secondary)]">
        {label}
      </label>
      <Input
        id={inputId}
        value={text}
        onChange={(event) => {
          setText(event.target.value)
          emit(event.target.value)
        }}
        onBlur={() => {
          const normalized = parseListInput(text)
          emit(text)
          setText(normalized.join(', '))
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            emit(text)
            setText(parseListInput(text).join(', '))
            event.currentTarget.blur()
          }
        }}
        placeholder={placeholder}
        className="mt-1.5"
      />
      <p className="mt-1 text-xs text-[var(--text-tertiary)]">{hint}</p>
      {value.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {value.map((item) => (
            <Badge
              key={item}
              variant="default"
              removable
              onRemove={() => onChange(value.filter((entry) => entry !== item))}
            >
              {item}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}

export function LinesInput({
  label,
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string
  value: string[]
  onChange: (values: string[]) => void
  placeholder: string
  hint: string
}) {
  const inputId = useId()
  const [text, setText] = useState(value.join('\n'))
  const lastEmitted = useRef(value)

  useEffect(() => {
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
      .slice(0, 5)
    lastEmitted.current = next
    onChange(next)
  }

  return (
    <div className="min-w-0">
      <label htmlFor={inputId} className="block text-xs font-medium text-[var(--text-secondary)]">
        {label}
      </label>
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
              .slice(0, 5)
              .join('\n'),
          )
        }}
        placeholder={placeholder}
        rows={3}
        className="mt-1.5"
      />
      <p className="mt-1 text-xs text-[var(--text-tertiary)]">{hint}</p>
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
  ].filter((chip) => chip.values.length > 0)

  if (chips.length === 0) {
    return <span className="text-xs text-[var(--text-tertiary)]">{copy.writePolicyNoMatch}</span>
  }

  return (
    <>
      {chips.map((chip) => (
        <Badge key={chip.label} variant="default" className="max-w-full">
          <span className="text-[var(--text-tertiary)]">{chip.label}</span>
          <span className="truncate">{chip.values.join(', ')}</span>
        </Badge>
      ))}
    </>
  )
}

export function MatchEditor({
  match,
  onMatchChange,
  hint,
  warning,
  copy,
}: {
  match: WritePolicyRuleMatch
  onMatchChange: (key: keyof WritePolicyRuleMatch, values: string[]) => void
  hint: string
  warning: string
  copy: Record<string, string>
}) {
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
        />
        <ListInput
          label={copy.writePolicyType}
          value={match.type}
          onChange={(values) => onMatchChange('type', values)}
          placeholder="decision, lesson"
          hint={copy.writePolicyTypeHint}
        />
        <ListInput
          label={copy.writePolicyTags}
          value={match.tags}
          onChange={(values) => onMatchChange('tags', values)}
          placeholder="pinned"
          hint={copy.writePolicyTagsHint}
        />
        <ListInput
          label={copy.writePolicyKeyword}
          value={match.keyword}
          onChange={(values) => onMatchChange('keyword', values)}
          placeholder="必须保留, ECONNRESET"
          hint={copy.writePolicyKeywordHint}
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
