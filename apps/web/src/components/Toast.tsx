/* eslint-disable react-refresh/only-export-components */
import {
  memo,
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  type ReactNode,
} from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CheckCircle2, XCircle, Info, AlertTriangle, X } from 'lucide-react'
import { useTranslation } from '../i18n/I18nProvider'
import { spring } from '../lib/motion'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface Toast {
  id: number
  message: string
  type: ToastType
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void
}

const ToastContext = createContext<ToastContextValue>({ toast: () => {} })

export function useToast() {
  return useContext(ToastContext)
}

let nextId = 0
const MAX_TOASTS = 5

const ICONS: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
}

const STYLES: Record<ToastType, string> = {
  success: 'bg-success-bg text-success-fg border border-success-border',
  error: 'bg-danger-bg text-danger-fg border border-danger-border',
  warning: 'bg-warning-bg text-warning-fg border border-warning-border',
  info: 'bg-info-bg text-info-fg border border-info-border',
}

const PROGRESS_COLORS: Record<ToastType, string> = {
  success: 'bg-success',
  error: 'bg-danger',
  warning: 'bg-warning',
  info: 'bg-info',
}

const DURATIONS: Record<ToastType, number> = {
  success: 3000,
  error: 5000,
  warning: 4000,
  info: 3000,
}

const ToastItem = memo(function ToastItem({
  item,
  onDismiss,
}: {
  item: Toast
  onDismiss: (id: number) => void
}) {
  const { t } = useTranslation()
  const Icon = ICONS[item.type]
  const duration = DURATIONS[item.type]
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const remainingRef = useRef(duration)
  const startTimeRef = useRef(Date.now())
  const [progress, setProgress] = useState(100)
  const [paused, setPaused] = useState(false)
  const rafRef = useRef<number | null>(null)

  const clearTimers = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [])

  const startProgress = useCallback(() => {
    startTimeRef.current = Date.now()
    const tick = () => {
      const elapsed = Date.now() - startTimeRef.current
      const pct = Math.max(0, ((remainingRef.current - elapsed) / duration) * 100)
      setProgress(pct)
      if (pct > 0) {
        rafRef.current = requestAnimationFrame(tick)
      }
    }
    rafRef.current = requestAnimationFrame(tick)
    timerRef.current = setTimeout(() => {
      onDismiss(item.id)
    }, remainingRef.current)
  }, [duration, item.id, onDismiss])

  useEffect(() => {
    if (!paused) {
      startProgress()
    }
    return clearTimers
  }, [paused, startProgress, clearTimers])

  const handlePause = useCallback(() => {
    clearTimers()
    remainingRef.current = Math.max(0, remainingRef.current - (Date.now() - startTimeRef.current))
    setPaused(true)
  }, [clearTimers])

  const handleResume = useCallback(() => {
    setPaused(false)
  }, [])

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 16, scale: 0.95 }}
      transition={{ type: 'spring', ...spring.snappy }}
      onMouseEnter={handlePause}
      onMouseLeave={handleResume}
      className={`pointer-events-auto relative overflow-hidden flex items-center gap-2 px-3.5 py-2.5 rounded-lg text-xs font-medium shadow-warm-md ${STYLES[item.type]}`}
    >
      <Icon size={14} className="shrink-0 opacity-90" aria-hidden="true" />
      <span className="flex-1 min-w-0 truncate">{item.message}</span>
      <button
        onClick={() => onDismiss(item.id)}
        className="p-1 opacity-60 hover:opacity-100 hover:bg-[var(--hover-subtle)] rounded-lg shrink-0 ml-1 transition-all duration-150 active:scale-95 select-none"
        aria-label={t.common.close}
      >
        <X size={14} aria-hidden="true" />
      </button>
      <div
        className={`absolute bottom-0 left-0 h-0.5 rounded-r-full transition-none ${PROGRESS_COLORS[item.type]} opacity-40`}
        style={{ width: `${progress}%` }}
      />
    </motion.div>
  )
})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback((message: string, type: ToastType = 'info') => {
    const id = nextId++
    setToasts((prev) => {
      const next = [...prev, { id, message, type }]
      if (next.length > MAX_TOASTS) {
        return next.slice(next.length - MAX_TOASTS)
      }
      return next
    })
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-toast flex flex-col-reverse gap-2 pointer-events-none">
        <AnimatePresence>
          {toasts.map((item) => (
            <ToastItem key={item.id} item={item} onDismiss={dismiss} />
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  )
}
