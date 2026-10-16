import { motion } from 'framer-motion'
import type { ReactNode } from 'react'
import { spring, duration } from '../lib/motion'

interface EmptyStateProps {
  icon?: ReactNode
  illustration?: ReactNode
  message: string
  description?: string
  action?: ReactNode
  compact?: boolean
}

export default function EmptyState({
  icon,
  illustration,
  message,
  description,
  action,
  compact = false,
}: EmptyStateProps) {
  return (
    <motion.div
      className={`flex flex-col items-center justify-center text-center ${compact ? 'py-6' : 'py-10 md:py-16'}`}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: duration.stagger }}
    >
      {illustration ? (
        <motion.div
          className="relative mb-5"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ ...spring.snappy, delay: 0 }}
        >
          <div className="flex items-center justify-center w-[100px] h-[100px]">{illustration}</div>
        </motion.div>
      ) : icon ? (
        <motion.div
          className="relative mb-5"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ ...spring.snappy, delay: 0 }}
        >
          <div className="relative flex items-center justify-center w-14 h-14 rounded-xl bg-surface-elevated/50 ring-1 ring-brand-200/40 border border-brand-200/25 shadow-warm-sm">
            {icon}
          </div>
        </motion.div>
      ) : null}
      <motion.p
        className="text-[var(--text-secondary)] text-sm font-medium mb-1"
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...spring.snappy, delay: 0.1 }}
      >
        {message}
      </motion.p>
      {description && (
        <motion.p
          className="text-[var(--text-tertiary)] text-xs max-w-xs leading-relaxed"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...spring.snappy, delay: 0.15 }}
        >
          {description}
        </motion.p>
      )}
      {action && (
        <motion.div
          className="mt-4"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...spring.snappy, delay: 0.2 }}
        >
          {action}
        </motion.div>
      )}
    </motion.div>
  )
}
