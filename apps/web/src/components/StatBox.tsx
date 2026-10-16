import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { spring } from '../lib/motion'
import { Card } from './ui/Card'

type StatColor = 'success' | 'danger' | 'warning' | 'info' | 'brand' | 'blue'

const COLORS: Record<StatColor, { bar: string; text: string; label: string }> = {
  success: {
    bar: 'border-l-success',
    text: 'text-success-fg',
    label: 'text-success-fg',
  },
  danger: {
    bar: 'border-l-danger',
    text: 'text-danger-fg',
    label: 'text-danger-fg',
  },
  warning: {
    bar: 'border-l-warning',
    text: 'text-warning-fg',
    label: 'text-warning-fg',
  },
  info: {
    bar: 'border-l-info',
    text: 'text-info-fg',
    label: 'text-info-fg',
  },
  brand: {
    bar: 'border-l-brand-500',
    text: 'text-brand-fg',
    label: 'text-brand-fg',
  },
  blue: {
    bar: 'border-l-brand-500',
    text: 'text-brand-fg',
    label: 'text-brand-fg',
  },
}

interface StatBoxProps {
  value: ReactNode
  label: string
  color: StatColor
  size?: 'md' | 'lg'
  className?: string
}

const SIZE_CONFIG = {
  md: { padding: 'py-3 px-4', value: 'text-3xl', gap: 'gap-3' },
  lg: { padding: 'py-4 px-5', value: 'text-4xl', gap: 'gap-3.5' },
} as const

export default function StatBox({
  value,
  label,
  color,
  size = 'md',
  className = '',
}: StatBoxProps) {
  const c = COLORS[color]
  const s = SIZE_CONFIG[size]

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={spring.snappy}
    >
      <Card className={`flex ${s.gap} items-start ${s.padding} border-l-4 ${c.bar} ${className}`}>
        <div className="min-w-0">
          <div className={`${s.value} font-bold ${c.text} tabular-nums leading-tight`}>{value}</div>
          <div className={`text-sm ${c.label} mt-1 truncate font-medium`}>{label}</div>
        </div>
      </Card>
    </motion.div>
  )
}
