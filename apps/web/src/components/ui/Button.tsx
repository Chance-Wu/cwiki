import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { motion, type HTMLMotionProps } from 'framer-motion'
import { spring } from '../../lib/motion'
import { twMerge } from 'tailwind-merge'

export type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'ghost'
  | 'danger'
  | 'success'
  | 'warning'
  | 'brand-outline'
  | 'subtle'
  | 'icon'
export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  asChild?: boolean
  children: ReactNode
}

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    'bg-gradient-to-b from-brand-300 to-brand-500 text-[var(--on-brand)] hover:from-brand-400 hover:to-brand-600 active:from-brand-500 active:to-brand-700 shadow-sm shadow-brand-500/20 disabled:bg-surface-inset disabled:text-[var(--text-tertiary)] disabled:shadow-none',
  secondary:
    'glass text-[var(--text-primary)] border border-[var(--glass-border)] hover:border-[var(--glass-border-hover)] hover:shadow-warm-sm active:bg-surface-inset/50 disabled:text-[var(--text-tertiary)] disabled:opacity-50',
  ghost:
    'text-[var(--text-secondary)] hover:bg-surface-inset hover:text-[var(--text-primary)] active:bg-surface-inset/80 disabled:text-[var(--text-tertiary)] disabled:hover:bg-transparent disabled:hover:text-[var(--text-tertiary)]',
  danger:
    'bg-danger text-[var(--on-accent)] hover:bg-danger/90 active:bg-danger/80 shadow-sm disabled:bg-surface-inset disabled:text-[var(--text-tertiary)] disabled:shadow-none',
  success:
    'bg-success text-[var(--on-accent)] hover:bg-success/90 active:bg-success/80 shadow-sm disabled:bg-surface-inset disabled:text-[var(--text-tertiary)] disabled:shadow-none',
  warning:
    'bg-warning text-[var(--on-accent)] hover:bg-warning/90 active:bg-warning/80 shadow-sm disabled:bg-surface-inset disabled:text-[var(--text-tertiary)] disabled:shadow-none',
  'brand-outline':
    'border border-brand-300/50 text-brand-fg hover:border-brand-300/70 hover:bg-brand-100/20 active:bg-brand-100/30 disabled:text-[var(--text-tertiary)] disabled:opacity-50 disabled:shadow-none',
  subtle:
    'bg-surface-elevated/50 text-[var(--text-secondary)] border border-[var(--glass-border)] hover:bg-surface-card-hover hover:border-[var(--glass-border-hover)] active:bg-surface-inset disabled:text-[var(--text-tertiary)] disabled:hover:bg-surface-inset',
  icon: 'text-[var(--text-secondary)] hover:bg-surface-inset hover:text-[var(--text-primary)] active:bg-surface-inset/80 disabled:text-[var(--text-tertiary)] disabled:hover:bg-transparent disabled:hover:text-[var(--text-tertiary)]',
}

const sizeClasses: Record<ButtonSize, string> = {
  xs: 'text-xs px-2 py-1 gap-1',
  sm: 'text-xs px-3 py-1.5 gap-1.5',
  md: 'text-sm px-4 py-2 gap-2',
  lg: 'text-base px-5 py-2.5 gap-2',
}

const springTap = spring.snappy

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', asChild, className, disabled, children, ...props }, ref) => {
    const classes = twMerge(
      'inline-flex items-center justify-center font-medium rounded-lg transition-[background-color,border-color,box-shadow,transform] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-200/50',
      'disabled:cursor-not-allowed',
      variantClasses[variant],
      sizeClasses[size],
      className,
    )

    if (asChild) {
      const MotionComponent = motion.span as unknown as React.ElementType
      return (
        <MotionComponent
          whileTap={{ scale: 0.98 }}
          whileHover={{ filter: 'brightness(1.05)' }}
          transition={springTap}
          className={classes}
        >
          {children}
        </MotionComponent>
      )
    }

    return (
      <motion.button
        ref={ref}
        whileTap={{ scale: disabled ? 1 : 0.98 }}
        whileHover={{ filter: 'brightness(1.05)' }}
        transition={springTap}
        className={classes}
        disabled={disabled}
        {...(props as unknown as HTMLMotionProps<'button'>)}
      >
        {children}
      </motion.button>
    )
  },
)
Button.displayName = 'Button'
