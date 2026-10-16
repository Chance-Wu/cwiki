import { AlertTriangle } from 'lucide-react'
import { motion } from 'framer-motion'
import { ease, duration } from '../lib/motion'

interface ErrorAlertProps {
  message: string
  className?: string
  onDismiss?: () => void
  dismissLabel?: string
  onRetry?: () => void
  retryLabel?: string
}

export default function ErrorAlert({
  message,
  className = '',
  onDismiss,
  dismissLabel,
  onRetry,
  retryLabel,
}: ErrorAlertProps) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: duration.slow, ease: ease.bounce }}
      className={`flex items-start gap-3 px-4 py-3.5 bg-danger-bg border border-danger-border rounded-lg text-sm text-danger-fg shadow-warm-sm ${className}`}
    >
      <motion.div
        initial={{ rotate: 0 }}
        animate={{ rotate: [0, -8, 8, -4, 0] }}
        transition={{ duration: duration.medium, delay: 0.2 }}
        className="shrink-0 mt-0.5"
      >
        <AlertTriangle size={16} className="text-danger-fg" aria-hidden="true" />
      </motion.div>
      <div className="flex-1">
        {message}
        {onRetry && (
          <motion.button
            onClick={onRetry}
            whileTap={{ scale: 0.97 }}
            className="ml-2 font-medium text-danger-fg hover:opacity-70 underline underline-offset-2 transition-opacity duration-150 select-none"
          >
            {retryLabel ?? 'Retry'}
          </motion.button>
        )}
        {onDismiss && (
          <motion.button
            onClick={onDismiss}
            whileTap={{ scale: 0.97 }}
            className="ml-2 font-medium text-danger-fg hover:opacity-70 underline underline-offset-2 transition-opacity duration-150 select-none"
          >
            {dismissLabel}
          </motion.button>
        )}
      </div>
    </motion.div>
  )
}
