import { useMemo, lazy, Suspense } from 'react'
import { motion, type Variants } from 'framer-motion'
import { Loader2, AlertTriangle, CheckCircle2, Clock, LayoutDashboard } from 'lucide-react'
import { spring } from '../lib/motion'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from '../i18n/I18nProvider'
import { CardSkeleton } from '../components/Skeleton'
import LoadingWrapper from '../components/LoadingWrapper'
import ErrorAlert from '../components/ErrorAlert'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import StatCard from '../components/StatCard'
import { Button } from '../components/ui/Button'
import { useDashboardStats, useDefaultWorkspace, useReviewStats } from '../hooks/useDashboard'
import DiagnosticsPanel from '../components/home/DiagnosticsPanel'
const EvolutionPanel = lazy(() => import('../components/home/EvolutionPanel'))
const LearningPanel = lazy(() => import('../components/home/LearningPanel'))

const bentoVariants: Variants = {
  hidden: { opacity: 0, y: 80, scale: 0.85, rotate: 3 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    scale: 1,
    rotate: 0,
    transition: {
      type: 'spring',
      stiffness: 260,
      damping: 14,
      mass: 0.9,
      delay: 0.4 + i * 0.15,
    },
  }),
}

export default function HomePage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const workspaceQuery = useDefaultWorkspace()
  const statsQuery = useDashboardStats()
  const reviewStatsQuery = useReviewStats(workspaceQuery.data)

  const loading = workspaceQuery.isLoading || statsQuery.isLoading
  const error = !workspaceQuery.data && statsQuery.isError
  const isRefetching = statsQuery.isRefetching

  const stats = useMemo(
    () => statsQuery.data ?? { candidates: 0, high_value: 0, conflicts: 0, approved: 0 },
    [statsQuery.data],
  )
  const reviewTrend = reviewStatsQuery.data?.review_trend?.map((d) => d.count) ?? []

  const statCards = useMemo(
    () => [
      {
        label: t.home.candidates,
        value: stats.candidates,
        icon: Clock,
        tone: 'warning' as const,
        subValue: stats.high_value > 0 ? `${t.home.highValue} ${stats.high_value}` : undefined,
        to: '/pending',
      },
      {
        label: t.home.conflicts,
        value: stats.conflicts,
        icon: AlertTriangle,
        tone: 'danger' as const,
        to: '/pending?tab=conflicts',
      },
      {
        label: t.home.approved,
        value: stats.approved,
        icon: CheckCircle2,
        tone: 'success' as const,
        to: '/memories',
      },
    ],
    [t.home.candidates, t.home.highValue, t.home.conflicts, t.home.approved, stats],
  )

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['dashboardStats'] })
    queryClient.invalidateQueries({ queryKey: ['reviewStats'] })
    queryClient.invalidateQueries({ queryKey: ['memoryStatus'] })
    queryClient.invalidateQueries({ queryKey: ['learningSuggestions'] })
    queryClient.invalidateQueries({ queryKey: ['task-queue-status'] })
    queryClient.invalidateQueries({ queryKey: ['consistency'] })
    queryClient.invalidateQueries({ queryKey: ['health'] })
  }

  return (
    <PageShell
      maxWidth="max-w-6xl"
      header={
        <motion.div
          className="flex items-center justify-between"
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={spring.bouncy}
        >
          <PageTitle icon={<LayoutDashboard size={18} />} title={t.home.title} />
          <Button onClick={handleRefresh} disabled={loading || isRefetching} variant="secondary">
            <Loader2 size={14} className={loading || isRefetching ? 'animate-spin' : ''} />
            {t.common.refresh}
          </Button>
        </motion.div>
      }
    >
      {/* ═══ 极光背景 ═══ */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden z-0">
        <motion.div
          className="aurora-blob aurora-blob-1"
          style={{
            width: '40vw',
            height: '40vw',
            top: '-10%',
            left: '-5%',
            background: 'radial-gradient(circle, rgb(var(--brand-rgb) / 0.15), transparent 70%)',
          }}
          animate={{
            x: [0, 30, -20, 0],
            y: [0, -20, 15, 0],
            scale: [1, 1.08, 0.95, 1],
          }}
          transition={{
            duration: 12,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
        <motion.div
          className="aurora-blob aurora-blob-2"
          style={{
            width: '35vw',
            height: '35vw',
            top: '20%',
            right: '-8%',
            background:
              'radial-gradient(circle, rgb(var(--accent-cyan-rgb) / 0.12), transparent 70%)',
          }}
          animate={{
            x: [0, -25, 15, 0],
            y: [0, 20, -10, 0],
            scale: [1, 0.92, 1.06, 1],
          }}
          transition={{
            duration: 15,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
        <motion.div
          className="aurora-blob aurora-blob-3"
          style={{
            width: '30vw',
            height: '30vw',
            bottom: '-5%',
            left: '30%',
            background:
              'radial-gradient(circle, rgb(var(--accent-violet-rgb) / 0.10), transparent 70%)',
          }}
          animate={{
            x: [0, 20, -15, 0],
            y: [0, -15, 20, 0],
            scale: [1, 1.05, 0.93, 1],
          }}
          transition={{
            duration: 18,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
      </div>

      {/* ═══ 内容 ═══ */}
      <div className="relative z-10">
        {error ? (
          <ErrorAlert
            message={t.home.loadFailed}
            onRetry={handleRefresh}
            retryLabel={t.common.retry}
          />
        ) : (
          <LoadingWrapper
            loading={loading}
            skeleton={
              <>
                <CardSkeleton cols={3} />
                <div className="space-y-3 md:space-y-4 mt-5">
                  {Array.from({ length: 2 }).map((_, i) => (
                    <div key={i} className="glass-card p-5 md:p-6 space-y-3 rounded-2xl">
                      <div className="h-3.5 w-20 shimmer rounded-xl" />
                      <div className="space-y-2">
                        {Array.from({ length: 4 }).map((__, j) => (
                          <div key={j} className="h-2.5 shimmer rounded-xl" />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            }
          >
            <>
              {/* 统计卡片 */}
              <div className="relative grid grid-cols-2 md:grid-cols-3 gap-4 mb-5 md:mb-6">
                {statCards.map(({ label, value, icon: Icon, tone, subValue, to }, i) => (
                  <StatCard
                    key={label}
                    label={label}
                    value={value}
                    Icon={Icon}
                    tone={tone}
                    trend={reviewTrend}
                    subValue={subValue}
                    to={to}
                    index={i}
                  />
                ))}
              </div>

              {/* 系统诊断卡片 */}
              <div className="mb-5 md:mb-6">
                <DiagnosticsPanel />
              </div>

              {/* Bento 网格 */}
              <motion.div
                className="grid grid-cols-1 md:grid-cols-12 gap-4 mb-5 md:mb-6"
                initial="hidden"
                animate="show"
                variants={{
                  hidden: {},
                  show: { transition: { staggerChildren: 0.1, delayChildren: 0.3 } },
                }}
              >
                {/* 演化指标 */}
                <motion.div className="md:col-span-12" variants={bentoVariants} custom={0}>
                  <Suspense fallback={null}>
                    <EvolutionPanel workspaceId={workspaceQuery.data} />
                  </Suspense>
                </motion.div>

                {/* 学习助手 */}
                <motion.div className="md:col-span-12" variants={bentoVariants} custom={1}>
                  <Suspense fallback={null}>
                    <LearningPanel workspaceId={workspaceQuery.data} />
                  </Suspense>
                </motion.div>
              </motion.div>
            </>
          </LoadingWrapper>
        )}
      </div>
    </PageShell>
  )
}
