import { useState } from 'react'
import { Check, Minus, Plus, Target, X } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { Card } from '../ui/Card'
import { clampGoal } from './reviewSessionUtils'

interface DailyGoalRingProps {
  done: number
  goal: number
  onChange: (goal: number) => void
}

export function DailyGoalRing({ done, goal, onChange }: DailyGoalRingProps) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(goal))

  const pct = goal > 0 ? Math.min(100, (done / goal) * 100) : 0
  const reached = done >= goal

  const r = 17
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - pct / 100)
  const strokeColor = reached ? 'rgb(var(--success-rgb))' : 'rgb(var(--brand-rgb))'

  const startEdit = () => {
    setDraft(String(goal))
    setEditing(true)
  }

  const commit = (value: number) => {
    const next = clampGoal(value)
    onChange(next)
    setDraft(String(next))
  }

  return (
    <Card className="mb-5 flex flex-wrap items-center gap-3 p-3 md:p-4">
      <button
        type="button"
        onClick={() => {
          if (!editing) startEdit()
        }}
        aria-label={t.review.dailyGoalEdit}
        className="relative shrink-0 rounded-full"
      >
        <svg width="44" height="44" viewBox="0 0 44 44" className="-rotate-90">
          <circle cx="22" cy="22" r={r} fill="none" stroke="var(--surface-inset)" strokeWidth="4" />
          <circle
            cx="22"
            cy="22"
            r={r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="4"
            strokeDasharray={circ}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 0.5s ease, stroke 0.3s ease' }}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-[11px] font-semibold tabular-nums text-[var(--text-primary)]">
          {Math.round(pct)}%
        </span>
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Target
            size={13}
            className={reached ? 'text-success-fg' : 'text-brand-fg'}
            aria-hidden="true"
          />
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {t.review.dailyGoal}
          </span>
        </div>
        {reached ? (
          <p className="mt-0.5 text-xs font-medium text-success-fg">{t.review.goalReached}</p>
        ) : (
          <p className="mt-0.5 text-xs tabular-nums text-[var(--text-tertiary)]">
            {done} / {goal}
          </p>
        )}
      </div>

      {editing ? (
        <div className="ml-auto flex w-full items-center justify-end gap-1 sm:w-auto">
          <button
            type="button"
            onClick={() => commit(goal - 1)}
            className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--text-secondary)] transition-colors hover:bg-surface-inset hover:text-[var(--text-primary)]"
            aria-label="-1"
          >
            <Minus size={13} aria-hidden="true" />
          </button>
          <input
            type="number"
            inputMode="numeric"
            value={draft}
            min={1}
            max={200}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                commit(Number(draft))
                setEditing(false)
              } else if (e.key === 'Escape') {
                setEditing(false)
              }
            }}
            className="w-14 rounded-md border border-[var(--border-default)] bg-surface-card px-1.5 py-1 text-center text-xs font-medium tabular-nums text-[var(--text-primary)] outline-none focus-visible:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-200/30"
            aria-label={t.review.dailyGoal}
          />
          <button
            type="button"
            onClick={() => commit(goal + 1)}
            className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--text-secondary)] transition-colors hover:bg-surface-inset hover:text-[var(--text-primary)]"
            aria-label="+1"
          >
            <Plus size={13} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => {
              commit(Number(draft))
              setEditing(false)
            }}
            className="flex h-7 w-7 items-center justify-center rounded-md text-success-fg transition-colors hover:bg-success/15"
            aria-label={t.review.dailyGoalSave}
          >
            <Check size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--text-tertiary)] transition-colors hover:bg-surface-inset hover:text-[var(--text-secondary)]"
            aria-label={t.common.cancel}
          >
            <X size={13} aria-hidden="true" />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={startEdit}
          className="ml-auto shrink-0 text-xs font-medium text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-secondary)]"
        >
          {t.review.dailyGoalEdit}
        </button>
      )}
    </Card>
  )
}
