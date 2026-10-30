import { useMemo, lazy, Suspense } from 'react'
import { motion, type Variants } from 'framer-motion'
import {
  Loader2,
  AlertTriangle,
  Clock,
  FileText,
  LayoutDashboard,
  BookOpenCheck,
  RefreshCw,
} from 'lucide-react'
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
import { useDashboardStats, useDefaultWorkspace } from '../hooks/useDashboard'
import { useReviewStats } from '../hooks/useReview'
import HealthAlert from '../components/home/HealthAlert'
import WeeklyReview from '../components/home/WeeklyReview'
import WorkspaceOverview from '../components/home/WorkspaceOverview'
const EvolutionPanel = lazy(() => import('../components/home/EvolutionPanel'))
const LearningPanel = lazy(() => import('../components/home/LearningPanel'))

const bentoVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.3,
      ease: 'easeOut',
      delay: 0.15 + i * 0.08,
    },
  }),
}

export default function HomePage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const workspaceQuery = useDefaultWorkspace()
  const statsQuery = useDashboardStats()
  const reviewStatsQuery = useReviewStats()

  const loading = workspaceQuery.isLoading || statsQuery.isLoading
  const error = !workspaceQuery.data && statsQuery.isError
  const isRefetching = statsQuery.isRefetching

  const stats = useMemo(
    () =>
      statsQuery.data ?? {
        candidates: 0,
        high_value: 0,
        conflicts: 0,
        approved: 0,
        pending_notes: 0,
      },
    [statsQuery.data],
  )
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
        label: t.notes.pending,
        value: stats.pending_notes,
        icon: FileText,
        tone: 'brand' as const,
        to: '/notes',
      },
      {
        label: t.home.conflicts,
        value: stats.conflicts,
        icon: AlertTriangle,
        tone: 'danger' as const,
        to: '/pending?tab=conflicts',
      },
      {
        label: t.home.dueReview,
        value: reviewStatsQuery.data?.due_now ?? 0,
        icon: BookOpenCheck,
        tone: 'info' as const,
        to: '/review',
      },
    ],
    [
      t.home.candidates,
      t.home.highValue,
      t.home.conflicts,
      t.home.dueReview,
      t.notes.pending,
      stats,
      reviewStatsQuery.data,
    ],
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
            {loading || isRefetching ? (
              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw size={14} aria-hidden="true" />
            )}
            {t.common.refresh}
          </Button>
        </motion.div>
      }
    >
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
                <CardSkeleton cols={4} />
                <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
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
              <div className="relative grid grid-cols-2 md:grid-cols-4 gap-4 mb-5 md:mb-6">
                {statCards.map(({ label, value, icon: Icon, tone, subValue, to }, i) => (
                  <StatCard
                    key={label}
                    label={label}
                    value={value}
                    Icon={Icon}
                    tone={tone}
                    subValue={subValue}
                    to={to}
                    index={i}
                  />
                ))}
              </div>

              {/* 异常时才出现的诊断入口；一切正常时首页不占位 */}
              <HealthAlert />

              {/* 本周回顾 */}
              <div className="mb-5 md:mb-6">
                <WeeklyReview workspaceId={workspaceQuery.data} />
              </div>

              {/* Bento 网格：进化指标 / 学习助手 两列，每列一张宽卡 */}
              <motion.div
                className="grid grid-cols-1 gap-4 md:grid-cols-2"
                initial="hidden"
                animate="show"
                variants={{
                  hidden: {},
                  show: { transition: { staggerChildren: 0.1, delayChildren: 0.3 } },
                }}
              >
                {/* 演化指标 */}
                <motion.div variants={bentoVariants} custom={0} className="flex [&>*]:flex-1">
                  <Suspense fallback={null}>
                    <EvolutionPanel workspaceId={workspaceQuery.data} />
                  </Suspense>
                </motion.div>

                {/* 学习助手（含到期复习分区） */}
                <motion.div variants={bentoVariants} custom={1} className="flex [&>*]:flex-1">
                  <Suspense fallback={null}>
                    <LearningPanel workspaceId={workspaceQuery.data} />
                  </Suspense>
                </motion.div>
              </motion.div>

              {/* 工作区总览：多工作区下唯一的全局数据分布入口 */}
              <div className="mt-5 md:mt-6">
                <WorkspaceOverview defaultWorkspaceId={workspaceQuery.data} />
              </div>
            </>
          </LoadingWrapper>
        )}
      </div>
    </PageShell>
  )
}
