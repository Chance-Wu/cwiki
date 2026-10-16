import { type ReactNode } from 'react'
import { motion, type HTMLMotionProps } from 'framer-motion'
import { X } from 'lucide-react'
import { twMerge } from 'tailwind-merge'
import { spring } from '../../lib/motion'

type BadgeVariant = 'default' | 'brand' | 'success' | 'warning' | 'danger' | 'info'

interface BadgeProps extends HTMLMotionProps<'span'> {
  variant?: BadgeVariant
  children: ReactNode
  removable?: boolean
  onRemove?: () => void
  dot?: boolean
}

const variantClasses: Record<BadgeVariant, string> = {
  default:
    'bg-surface-elevated/60 border-[var(--glass-border)] text-[var(--text-secondary)] shadow-warm-xs',
  brand: 'bg-brand-100/70 border-brand-300/35 text-brand-fg shadow-warm-xs',
  success: 'bg-success/22 border-success/35 text-success-fg shadow-warm-xs',
  warning: 'bg-warning/22 border-warning/35 text-warning-fg shadow-warm-xs',
  danger: 'bg-danger/22 border-danger/35 text-danger-fg shadow-warm-xs',
  info: 'bg-info/22 border-info/35 text-info-fg shadow-warm-xs',
}

const dotColors: Record<BadgeVariant, string> = {
  default: 'bg-[var(--text-tertiary)]',
  brand: 'bg-brand-500',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
}

export function Badge({
  variant = 'default',
  className,
  children,
  removable,
  onRemove,
  dot,
  ...props
}: BadgeProps) {
  return (
    <motion.span
      layout
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.8 }}
      transition={spring.snappy}
      className={twMerge(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-xs font-medium border transition-colors duration-200 ease-out',
        variantClasses[variant],
        className,
      )}
      {...props}
    >
      {dot && <span className={twMerge('w-1.5 h-1.5 rounded-full', dotColors[variant])} />}
      {children}
      {removable && (
        <button
          type="button"
          onClick={onRemove}
          className="ml-0.5 -mr-0.5 p-0.5 rounded-full hover:bg-surface-card-hover hover:text-[var(--text-secondary)] active:scale-95 transition-all duration-150 ease-out"
          aria-label={typeof children === 'string' ? `Remove ${children}` : 'Remove'}
        >
          <X size={10} />
        </button>
      )}
    </motion.span>
  )
}
