import { useId } from 'react'
import { motion } from 'framer-motion'
import { spring } from '../../lib/motion'

interface SegmentedControlOption<T extends string> {
  value: T
  label: string
  count?: number
}

interface SegmentedControlProps<T extends string> {
  value: T
  onChange: (value: T) => void
  options: SegmentedControlOption<T>[]
  className?: string
}

export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  className = '',
}: SegmentedControlProps<T>) {
  const id = useId()

  return (
    <div
      className={`relative inline-flex items-center gap-0.5 p-0.5 glass rounded-lg border border-[var(--glass-border)] shadow-warm-xs ${className}`}
    >
      {options.map((option) => {
        const isActive = value === option.value
        return (
          <motion.button
            key={option.value}
            onClick={() => onChange(option.value)}
            className={`relative z-10 px-3 py-1.5 text-sm rounded-lg transition-colors duration-150 select-none ${
              isActive
                ? 'text-[var(--text-primary)] font-semibold'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
            whileTap={{ scale: 0.95 }}
            transition={spring.press}
          >
            {isActive && (
              <motion.div
                layoutId={`segmented-indicator-${id}`}
                className="absolute inset-0 rounded-lg bg-[rgb(var(--brand-rgb)/0.15)] backdrop-blur-[var(--glass-blur)] border border-[rgb(var(--brand-rgb)/0.25)]"
                style={{
                  boxShadow:
                    'inset 0 1px 0 rgba(255,255,255,0.5), 0 0 12px rgba(var(--brand-rgb),0.12)',
                }}
                transition={spring.snappy}
              />
            )}
            <span className="relative z-10 flex items-center gap-1.5">
              {option.label}
              {option.count !== undefined && (
                <span
                  className={`tabular-nums text-xs px-1.5 py-0.5 rounded-md ${
                    isActive
                      ? 'bg-[rgb(var(--brand-rgb)/0.2)] text-[var(--text-primary)] font-medium'
                      : 'bg-surface-elevated/40 text-[var(--text-tertiary)]'
                  }`}
                >
                  {option.count}
                </span>
              )}
            </span>
          </motion.button>
        )
      })}
    </div>
  )
}
