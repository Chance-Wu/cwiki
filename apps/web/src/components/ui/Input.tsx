import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { twMerge } from 'tailwind-merge'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode
}

const inputBase = twMerge(
  'w-full px-3 py-2 text-sm rounded-lg',
  'bg-surface-card backdrop-blur-[var(--glass-blur)]',
  'border border-[var(--glass-border)]',
  'text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]',
  'shadow-warm-xs',
  'transition-[border-color,box-shadow] duration-200 ease-out',
  'hover:border-[var(--glass-border-hover)] hover:shadow-warm-sm',
  'focus-visible:outline-none focus-visible:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-200/30 focus-visible:shadow-warm-sm',
  'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-[var(--glass-border)]',
)

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, icon, ...props }, ref) => {
    if (icon) {
      return (
        <div className="relative">
          <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none text-[var(--text-tertiary)]">
            {icon}
          </div>
          <input ref={ref} className={twMerge(inputBase, 'pl-10 pr-3', className)} {...props} />
        </div>
      )
    }

    return <input ref={ref} className={twMerge(inputBase, className)} {...props} />
  },
)
Input.displayName = 'Input'
