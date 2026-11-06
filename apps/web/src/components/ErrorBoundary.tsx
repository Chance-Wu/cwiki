import { Component, type ReactNode, type ErrorInfo } from 'react'
import { AlertTriangle, WifiOff, ShieldAlert, FileQuestion, Server } from 'lucide-react'
import { motion } from 'framer-motion'
import { I18nContext } from '../i18n/I18nProvider'
import type { TranslationKeys } from '../i18n/locales/en'
import { Button } from './ui/Button'
import { spring } from '../lib/motion'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/** 根据错误信息推断错误类型并返回对应图标 */
function getErrorIcon(error: Error | null) {
  if (!error) return AlertTriangle
  const msg = error.message.toLowerCase()
  if (msg.includes('网络') || msg.includes('network') || msg.includes('fetch')) return WifiOff
  if (msg.includes('鉴权') || msg.includes('auth') || msg.includes('token')) return ShieldAlert
  if (msg.includes('不存在') || msg.includes('not found') || msg.includes('404')) return FileQuestion
  if (msg.includes('服务器') || msg.includes('server') || msg.includes('500')) return Server
  return AlertTriangle
}

export class ErrorBoundary extends Component<Props, State> {
  static contextType = I18nContext
  declare context: React.ContextType<typeof I18nContext>

  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      const eb: TranslationKeys['errorBoundary'] | undefined = this.context?.t?.errorBoundary
      const title = eb?.title ?? 'Something went wrong'
      const unknownError = eb?.unknownError ?? 'An unknown error occurred while rendering'
      const retry = eb?.retry ?? 'Retry'

      const ErrorIcon = getErrorIcon(this.state.error)
      const errorMessage = this.state.error?.message || unknownError

      return (
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={spring.snappy}
          className="flex flex-col items-center justify-center py-16 px-4 text-center"
        >
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ ...spring.snappy, delay: 0.05 }}
            className="w-14 h-14 rounded-xl bg-surface-inset ring-1 ring-brand-border border border-brand-200/25 shadow-warm-xs flex items-center justify-center mb-3"
          >
            <ErrorIcon size={24} className="text-warning-fg" aria-hidden="true" />
          </motion.div>
          <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-1">{title}</h3>
          <p className="text-xs text-[var(--text-tertiary)] mb-4 max-w-md break-words">
            {errorMessage}
          </p>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={this.handleReset}>
              {retry}
            </Button>
            <Button
              variant="secondary"
              onClick={() => window.location.reload()}
            >
              {this.context?.t?.common?.refreshPage ?? 'Reload Page'}
            </Button>
          </div>
        </motion.div>
      )
    }
    return this.props.children
  }
}
