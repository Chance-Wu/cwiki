import { Component, type ReactNode, type ErrorInfo } from 'react'
import { AlertTriangle } from 'lucide-react'
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
            <AlertTriangle size={24} className="text-warning-fg" aria-hidden="true" />
          </motion.div>
          <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-1">{title}</h3>
          <p className="text-xs text-[var(--text-tertiary)] mb-4 max-w-md">
            {this.state.error?.message || unknownError}
          </p>
          <Button variant="secondary" onClick={this.handleReset}>
            {retry}
          </Button>
        </motion.div>
      )
    }
    return this.props.children
  }
}
