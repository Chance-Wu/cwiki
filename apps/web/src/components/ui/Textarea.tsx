import { forwardRef, type TextareaHTMLAttributes } from 'react'
import { twMerge } from 'tailwind-merge'

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => {
  return (
    <textarea
      ref={ref}
      className={twMerge(
        'w-full px-3 py-2 text-sm rounded-lg',
        'bg-surface-card backdrop-blur-[var(--glass-blur)]',
        'border border-[var(--glass-border)]',
        'text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]',
        'transition-[border-color,box-shadow] duration-200 ease-out',
        'hover:border-[var(--glass-border-hover)]',
        'focus-visible:outline-none focus-visible:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-200',
        'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-[var(--glass-border)]',
        'resize-y',
        className,
      )}
      {...props}
    />
  )
})
Textarea.displayName = 'Textarea'
