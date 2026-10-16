import { Bot, X } from 'lucide-react'
import { AGENT_COLORS, NEUTRAL_CHIP } from './constants'

export default function AgentBadge({
  agent,
  onRemove,
  removeTitle,
}: {
  agent: string
  onRemove?: () => void
  removeTitle?: string
}) {
  const color = AGENT_COLORS[agent] || NEUTRAL_CHIP
  return (
    <span
      className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded-lg text-xs font-medium max-w-[120px] border border-[var(--border-default)] shadow-warm-xs transition-all duration-150 ${color}`}
    >
      <Bot size={12} className="shrink-0" aria-hidden="true" />
      <span className="truncate">{agent}</span>
      {onRemove && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          className="ml-0.5 hover:opacity-70 transition-all duration-150 select-none"
          title={removeTitle}
          aria-label={removeTitle}
        >
          <X size={12} aria-hidden="true" />
        </button>
      )}
    </span>
  )
}
