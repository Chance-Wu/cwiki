import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { spring } from '../lib/motion'

interface PageTitleProps {
  icon: ReactNode
  title: string
  subtitle?: string
}

export default function PageTitle({ icon, title, subtitle }: PageTitleProps) {
  return (
    <motion.div
      className="flex items-start gap-3.5"
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={spring.snappy}
    >
      <motion.div
        className="flex items-center justify-center w-9 h-9 rounded-xl shrink-0 mt-0.5 border border-brand-200/40"
        style={{
          background: `linear-gradient(135deg, rgb(var(--brand-rgb) / 0.14), rgb(var(--brand-rgb) / 0.06))`,
          boxShadow: `0 1px 2px rgb(var(--brand-rgb) / 0.08), inset 0 1px 1px rgb(var(--brand-rgb) / 0.10)`,
        }}
        initial={{ scale: 0.85, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ ...spring.snappy, delay: 0.03 }}
      >
        <div style={{ color: `rgb(var(--brand-text-rgb))` }}>{icon}</div>
      </motion.div>
      <div>
        <h1 className="text-xl md:text-2xl font-serif font-semibold text-[var(--text-primary)] tracking-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-0.5 text-xs text-[var(--text-tertiary)] font-medium">{subtitle}</p>
        )}
      </div>
    </motion.div>
  )
}
