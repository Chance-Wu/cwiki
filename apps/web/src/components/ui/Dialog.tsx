import { type ReactNode } from 'react'
import * as RadixDialog from '@radix-ui/react-dialog'
import { motion, AnimatePresence } from 'framer-motion'
import { X } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { duration, spring, ease } from '../../lib/motion'

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
  size?: 'sm' | 'md' | 'lg' | 'xl'
  titleLayoutId?: string
  footer?: ReactNode
  fixedHeight?: boolean
}

const sizeClasses: Record<string, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  size = 'md',
  titleLayoutId,
  footer,
  fixedHeight,
}: DialogProps) {
  const { t } = useTranslation()
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <RadixDialog.Portal forceMount>
            <RadixDialog.Overlay asChild>
              <motion.div
                className="fixed inset-0 z-dialog bg-surface-overlay backdrop-blur-[var(--glass-blur)]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: duration.modal, ease: ease.bounce }}
                onClick={() => onOpenChange(false)}
              />
            </RadixDialog.Overlay>
            <RadixDialog.Content
              className="fixed inset-0 z-dialog flex items-center justify-center pointer-events-none"
              style={{ pointerEvents: 'none' }}
              forceMount
            >
              <motion.div
                className={`pointer-events-auto w-[calc(100%-2rem)] ${sizeClasses[size]} ${fixedHeight ? 'h-[85vh] flex flex-col' : 'max-h-[85vh] overflow-y-auto scrollbar-thin'} glass-heavy rounded-2xl shadow-warm-lg focus:outline-none`}
                initial={{ opacity: 0, scale: 0.94, y: 16 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.96, y: 8 }}
                transition={{ type: 'spring', ...spring.dialog }}
              >
                {fixedHeight ? (
                  <>
                    <div className="px-6 pt-5 pb-3 shrink-0">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <RadixDialog.Title className="text-lg font-semibold text-[var(--text-primary)]">
                            {titleLayoutId ? (
                              <motion.span layoutId={titleLayoutId} className="inline-block">
                                {title}
                              </motion.span>
                            ) : (
                              title
                            )}
                          </RadixDialog.Title>
                          {description && (
                            <RadixDialog.Description className="text-sm text-[var(--text-secondary)] mt-1">
                              {description}
                            </RadixDialog.Description>
                          )}
                        </div>
                        <RadixDialog.Close asChild>
                          <button
                            className="p-1 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-surface-inset transition-all duration-150 active:scale-95 select-none shrink-0"
                            aria-label={t.common.close}
                          >
                            <X size={16} aria-hidden="true" />
                          </button>
                        </RadixDialog.Close>
                      </div>
                    </div>

                    <div className="flex-1 min-h-0 overflow-hidden flex flex-col px-6">
                      {children}
                    </div>

                    {footer && (
                      <div className="px-6 py-3 shrink-0 border-t border-[var(--glass-border)]">
                        {footer}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <div className="px-6 pt-5 pb-3 shrink-0">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <RadixDialog.Title className="text-lg font-semibold text-[var(--text-primary)]">
                            {titleLayoutId ? (
                              <motion.span layoutId={titleLayoutId} className="inline-block">
                                {title}
                              </motion.span>
                            ) : (
                              title
                            )}
                          </RadixDialog.Title>
                          {description && (
                            <RadixDialog.Description className="text-sm text-[var(--text-secondary)] mt-1">
                              {description}
                            </RadixDialog.Description>
                          )}
                        </div>
                        <RadixDialog.Close asChild>
                          <button
                            className="p-1 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-surface-inset transition-all duration-150 active:scale-95 select-none shrink-0"
                            aria-label={t.common.close}
                          >
                            <X size={16} aria-hidden="true" />
                          </button>
                        </RadixDialog.Close>
                      </div>
                    </div>
                    <div className="px-6 pb-6 overflow-y-auto scrollbar-thin">{children}</div>
                    {footer && <div className="px-6 pb-5 shrink-0">{footer}</div>}
                  </>
                )}
              </motion.div>
            </RadixDialog.Content>
          </RadixDialog.Portal>
        )}
      </AnimatePresence>
    </RadixDialog.Root>
  )
}
