import * as RadixSwitch from '@radix-ui/react-switch'
import { motion } from 'framer-motion'
import { twMerge } from 'tailwind-merge'
import { spring } from '../../lib/motion'

interface SwitchProps {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  label?: string
  disabled?: boolean
  className?: string
}

const thumbVariants = {
  checked: { x: 18, scale: 1, scaleX: 1 },
  unchecked: { x: 2, scale: 1, scaleX: 1 },
}

export function Switch({ checked, onCheckedChange, label, disabled, className }: SwitchProps) {
  return (
    <div className={twMerge('flex items-center gap-2', className)}>
      <RadixSwitch.Root
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className={twMerge(
          'relative w-9 h-5 rounded-full transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-200/30 select-none',
          checked
            ? 'bg-brand-500 shadow-[inset_0_1px_3px_rgba(0,0,0,0.1),0_0_8px_rgba(var(--brand-rgb),0.3)]'
            : 'bg-[var(--border-strong)] shadow-inner',
          disabled
            ? 'opacity-30 saturate-0 cursor-not-allowed'
            : 'hover:brightness-110 active:scale-[0.97]',
        )}
      >
        <motion.div
          className="absolute top-0.5 w-4 h-4 bg-surface-card rounded-full shadow-warm-sm origin-center"
          variants={thumbVariants}
          animate={checked ? 'checked' : 'unchecked'}
          transition={spring.press}
          whileTap={{ scale: 0.85, scaleX: 1.15 }}
        />
      </RadixSwitch.Root>
      {label && (
        <span
          className={twMerge(
            'text-sm text-[var(--text-primary)]',
            disabled && 'opacity-30 saturate-0 cursor-not-allowed',
          )}
        >
          {label}
        </span>
      )}
    </div>
  )
}
