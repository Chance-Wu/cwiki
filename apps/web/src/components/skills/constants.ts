import { FolderOpen, Bot, Puzzle } from 'lucide-react'

export const NEUTRAL_CHIP =
  'bg-surface-elevated/50 text-[var(--text-secondary)] border border-[var(--border-default)]'

export const AGENT_BTN_ACTIVE = 'bg-brand-50 text-brand-fg border border-brand-200'
export const AGENT_BTN_INACTIVE =
  'bg-surface-elevated/30 text-[var(--text-secondary)] hover:bg-surface-card-hover'

export const SOURCE_CONFIG: Record<
  string,
  { icon: typeof FolderOpen; color: string; bg: string; ring: string }
> = {
  project: {
    icon: FolderOpen,
    color: 'text-[var(--text-secondary)]',
    bg: 'bg-surface-elevated/40',
    ring: 'ring-subtle',
  },
  qoder: {
    icon: Bot,
    color: 'text-[var(--text-secondary)]',
    bg: 'bg-surface-elevated/40',
    ring: 'ring-subtle',
  },
  codex: { icon: Bot, color: 'text-success-fg', bg: 'bg-success/22', ring: 'ring-success/35' },
  plugin: {
    icon: Puzzle,
    color: 'text-[var(--text-secondary)]',
    bg: 'bg-surface-elevated/40',
    ring: 'ring-subtle',
  },
}

export const SOURCE_BADGE: Record<string, string> = {
  project: NEUTRAL_CHIP,
  qoder: NEUTRAL_CHIP,
  codex: 'bg-success/22 text-success-fg border border-success/35',
  plugin: NEUTRAL_CHIP,
}

export const AGENT_COLORS: Record<string, string> = {
  qoder: NEUTRAL_CHIP,
  codex: 'bg-success/22 text-success-fg border border-success/35',
  zcode: 'bg-warning/22 text-warning-fg border border-warning/35',
}
