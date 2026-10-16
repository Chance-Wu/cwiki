import * as RadixSelect from '@radix-ui/react-select'
import { ChevronDown, Check } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTranslation } from '../../i18n/I18nProvider'
import { duration, ease } from '../../lib/motion'

interface SelectOption {
  value: string
  label: string
}

interface SelectProps {
  options: SelectOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  icon?: ReactNode
}

export function Select({ options, value, onChange, placeholder, icon }: SelectProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const displayPlaceholder = placeholder ?? t.common.select
  // Radix Select.Value 依赖 Content 内 ItemText 的注册来解析显示文本，
  // 实测当前版本触发器始终为空；受控模式下 value/options 都在手，直接自解析
  const selectedLabel =
    options.find((option) => option.value === value)?.label ?? displayPlaceholder

  return (
    <RadixSelect.Root value={value} onValueChange={onChange} open={open} onOpenChange={setOpen}>
      <RadixSelect.Trigger
        className="h-9 flex items-center gap-2 px-3 text-sm rounded-lg glass border border-[var(--glass-border)] bg-surface-card/80 backdrop-blur-[var(--glass-blur)] hover:border-[var(--glass-border-hover)] hover:bg-surface-card transition-all duration-200 ease-out focus-visible:outline-none focus-visible:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-200/30 select-none shadow-warm-xs"
        aria-label={t.common.select}
      >
        {icon && <span className="shrink-0 text-[var(--text-tertiary)]">{icon}</span>}
        <span className="flex-1 text-left truncate text-[var(--text-primary)]">
          {selectedLabel}
        </span>
        <RadixSelect.Icon>
          <ChevronDown
            size={14}
            className={`text-[var(--text-tertiary)] transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
            aria-hidden="true"
          />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>

      <RadixSelect.Portal>
        <AnimatePresence>
          {open && (
            <RadixSelect.Content
              position="popper"
              sideOffset={4}
              asChild
              forceMount
              className="z-dropdown glass-heavy rounded-lg shadow-warm-lg overflow-hidden"
            >
              <motion.div
                initial={{ opacity: 0, scale: 0.95, y: -4 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: -4 }}
                transition={{ duration: duration.normal, ease: ease.out }}
              >
                <RadixSelect.Viewport className="p-1 max-h-56">
                  {options.map((option) => (
                    <RadixSelect.Item
                      key={option.value}
                      value={option.value}
                      className="flex items-center gap-2.5 px-3 py-2 text-sm text-[var(--text-primary)] rounded-lg cursor-pointer select-none outline-none data-[highlighted]:bg-brand-500/12 data-[highlighted]:text-brand-fg data-[state=checked]:font-medium transition-all duration-150 active:scale-[0.98]"
                    >
                      <RadixSelect.ItemIndicator>
                        <Check size={14} className="text-[var(--text-primary)]" />
                      </RadixSelect.ItemIndicator>
                      <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                    </RadixSelect.Item>
                  ))}
                </RadixSelect.Viewport>
              </motion.div>
            </RadixSelect.Content>
          )}
        </AnimatePresence>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  )
}
