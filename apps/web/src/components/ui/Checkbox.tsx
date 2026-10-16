import * as RadixCheckbox from '@radix-ui/react-checkbox'
import { motion } from 'framer-motion'
import { Check, Minus } from 'lucide-react'
import { twMerge } from 'tailwind-merge'
import { spring } from '../../lib/motion'

interface CheckboxProps {
  checked: boolean | 'indeterminate'
  onCheckedChange: (checked: boolean) => void
  label?: string
  className?: string
}

const iconMotion = {
  initial: { scale: 0, opacity: 0 },
  animate: { scale: 1, opacity: 1 },
  exit: { scale: 0, opacity: 0 },
}

const MotionCheckboxRoot = motion.create(RadixCheckbox.Root)

export function Checkbox({ checked, onCheckedChange, label, className }: CheckboxProps) {
  return (
    <div className={twMerge('flex items-center gap-2', className)}>
      <MotionCheckboxRoot
        checked={checked}
        onCheckedChange={onCheckedChange}
        className="w-4 h-4 rounded border border-[var(--border-default)] bg-surface-card shadow-warm-xs transition-colors duration-150 data-[state=checked]:bg-brand-500 data-[state=checked]:border-brand-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-200/30 flex items-center justify-center hover:border-brand-300"
        whileTap={{ scale: 0.82 }}
        transition={spring.press}
      >
        <RadixCheckbox.Indicator>
          <motion.div
            {...iconMotion}
            transition={spring.snappy}
            className="flex items-center justify-center"
          >
            {checked === 'indeterminate' ? (
              <Minus size={12} className="text-[var(--on-brand)]" />
            ) : (
              <Check size={12} className="text-[var(--on-brand)]" />
            )}
          </motion.div>
        </RadixCheckbox.Indicator>
      </MotionCheckboxRoot>
      {label && <span className="text-sm text-[var(--text-primary)]">{label}</span>}
    </div>
  )
}
