import { memo } from 'react'
import { Link } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import { motion } from 'framer-motion'
import { useCountUp } from '../hooks/useCountUp'

export type StatTone = 'brand' | 'success' | 'warning' | 'danger' | 'info'

const TONES: Record<StatTone, { chip: string; ring: string; line: string; glow: string }> = {
  brand: {
    chip: 'bg-brand-100/70 text-brand-fg border border-brand-300/35 shadow-warm-xs',
    ring: 'ring-brand-300/30',
    line: 'var(--brand-rgb)',
    glow: 'rgba(var(--brand-rgb), 0.25)',
  },
  success: {
    chip: 'bg-success/22 border border-success/35 text-success-fg shadow-warm-xs',
    ring: 'ring-success/30',
    line: 'var(--success-rgb)',
    glow: 'rgba(var(--success-rgb), 0.25)',
  },
  warning: {
    chip: 'bg-warning/22 border border-warning/35 text-warning-fg shadow-warm-xs',
    ring: 'ring-warning/30',
    line: 'var(--warning-rgb)',
    glow: 'rgba(var(--warning-rgb), 0.25)',
  },
  danger: {
    chip: 'bg-danger/22 border border-danger/35 text-danger-fg shadow-warm-xs',
    ring: 'ring-danger/30',
    line: 'var(--danger-rgb)',
    glow: 'rgba(var(--danger-rgb), 0.25)',
  },
  info: {
    chip: 'bg-info/22 border border-info/35 text-info-fg shadow-warm-xs',
    ring: 'ring-info/30',
    line: 'var(--info-rgb)',
    glow: 'rgba(var(--info-rgb), 0.25)',
  },
}

interface StatCardProps {
  label: string
  value: number
  Icon: LucideIcon
  tone?: StatTone
  subValue?: string
  to?: string
  index?: number
}

const StatCard = memo(function StatCard({
  label,
  value,
  Icon,
  tone = 'brand',
  subValue,
  to,
  index = 0,
}: StatCardProps) {
  const animatedRef = useCountUp(value)
  const isEmpty = value === 0
  const t = TONES[tone]

  const card = (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.06, ease: 'easeOut' }}
      className={`glass-card group relative h-full overflow-hidden rounded-2xl p-5 md:p-6 transition-[box-shadow,border-color,transform] duration-300 ease-spring ${
        to ? 'cursor-pointer hover:-translate-y-0.5' : ''
      }`}
    >
      {/* 背景装饰 — 静态微弱光晕（去除呼吸动画以降开销） */}
      <div
        className="absolute -top-10 -right-10 h-32 w-32 rounded-full opacity-[0.08] pointer-events-none"
        style={{ background: `radial-gradient(circle, rgb(${t.line}), transparent 70%)` }}
      />

      <div className="relative z-20 flex h-full flex-col">
        <div className="mb-5 flex items-center justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div
              className={`flex items-center justify-center w-9 h-9 rounded-xl shrink-0 ring-1 ${t.ring} ${t.chip}`}
            >
              <Icon size={17} strokeWidth={2} aria-hidden="true" />
            </div>
            <p className="text-xs text-[var(--text-secondary)] font-medium truncate tracking-wide">
              {label}
            </p>
          </div>
        </div>

        <div className="mt-auto">
          <motion.p
            className={`leading-none tabular-nums ${
              isEmpty
                ? 'text-4xl md:text-5xl font-semibold text-[var(--text-tertiary)]'
                : 'text-5xl md:text-6xl font-bold tracking-tight text-[var(--text-primary)]'
            }`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.2 + index * 0.06 }}
          >
            <span ref={animatedRef}>0</span>
          </motion.p>

          {subValue && (
            <p className="text-xs text-[var(--text-tertiary)] mt-3 font-medium">{subValue}</p>
          )}
        </div>
      </div>
    </motion.div>
  )

  if (to) {
    return (
      <Link to={to} className="block h-full no-underline">
        {card}
      </Link>
    )
  }

  return card
})

export default StatCard
