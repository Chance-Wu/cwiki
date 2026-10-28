import { lazy, Suspense, useState, useEffect } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { I18nProvider, useTranslation } from './i18n/I18nProvider'
import Layout from './components/Layout'
import { Button } from './components/ui/Button'
import CommandPalette from './components/CommandPalette'
import { ToastProvider } from './components/Toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ListSkeleton } from './components/Skeleton'
import { supportsViewTransition } from './lib/history'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30000,
      retry: 1,
    },
    mutations: {
      onError: (error: Error) => {
        if (import.meta.env.DEV) {
          console.error('[QueryClient] mutation error:', error.message)
        }
      },
    },
  },
})

const HomePage = lazy(() => import('./pages/HomePage'))
const InboxPage = lazy(() => import('./pages/InboxPage'))
const NotesPage = lazy(() => import('./pages/NotesPage'))
const MemoriesPage = lazy(() => import('./pages/MemoriesPage'))
const SkillsPage = lazy(() => import('./pages/SkillsPage'))
const ReviewPage = lazy(() => import('./pages/ReviewPage'))
const ConfigPage = lazy(() => import('./pages/ConfigPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const GraphPage = lazy(() => import('./pages/GraphPage'))
const QualityPage = lazy(() => import('./pages/QualityPage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))

function ChunkErrorFallback() {
  const [retrying, setRetrying] = useState(false)
  const { t } = useTranslation()

  const handleRetry = () => {
    setRetrying(true)
    window.location.reload()
  }

  useEffect(() => {
    if (retrying) {
      setRetrying(false)
    }
  }, [retrying])

  return (
    <div className="flex flex-col items-center justify-center min-h-[50vh] p-8 text-center">
      <div className="w-12 h-12 mb-4 rounded-full bg-warning-bg flex items-center justify-center border border-warning-border">
        <svg
          className="w-6 h-6 text-warning-fg"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
          />
        </svg>
      </div>
      <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-2">
        {t.common.loadFailed}
      </h2>
      <p className="text-sm text-[var(--text-secondary)] mb-4">{t.common.loadFailedDesc}</p>
      <Button onClick={handleRetry}>{retrying ? t.common.refreshing : t.common.refreshPage}</Button>
    </div>
  )
}

function AnimatedRoutes() {
  const location = useLocation()
  const routes = (
    <Routes location={location}>
      <Route path="/" element={<HomePage />} />
      <Route path="/pending" element={<InboxPage />} />
      <Route path="/notes" element={<NotesPage />} />
      <Route path="/memories" element={<MemoriesPage />} />
      <Route path="/skills" element={<SkillsPage />} />
      <Route path="/review" element={<ReviewPage />} />
      <Route path="/config" element={<ConfigPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/graph" element={<GraphPage />} />
      <Route path="/quality" element={<QualityPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )

  if (supportsViewTransition) {
    return <div className="flex-1 min-h-0 flex flex-col">{routes}</div>
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={location.pathname}
        className="flex-1 min-h-0 flex flex-col"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        {routes}
      </motion.div>
    </AnimatePresence>
  )
}

export default function App() {
  const [chunkError, setChunkError] = useState(false)

  useEffect(() => {
    const handler = (event: PromiseRejectionEvent) => {
      if (
        event.reason?.message?.includes('Failed to fetch dynamically imported module') ||
        event.reason?.message?.includes('Loading chunk') ||
        event.reason?.message?.includes('Loading CSS')
      ) {
        event.preventDefault()
        setChunkError(true)
      }
    }
    window.addEventListener('unhandledrejection', handler)
    return () => window.removeEventListener('unhandledrejection', handler)
  }, [])

  if (chunkError) {
    return (
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <ChunkErrorFallback />
        </I18nProvider>
      </QueryClientProvider>
    )
  }

  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ErrorBoundary>
          <ToastProvider>
            <Layout>
              <CommandPalette />
              <Suspense
                fallback={
                  <div className="p-4 md:p-8 max-w-4xl mx-auto">
                    <ListSkeleton rows={4} />
                  </div>
                }
              >
                <AnimatedRoutes />
              </Suspense>
            </Layout>
          </ToastProvider>
        </ErrorBoundary>
      </I18nProvider>
    </QueryClientProvider>
  )
}
