import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Brain, ChevronDown, ChevronUp } from 'lucide-react'
import { typeLabel, TYPE_COLORS } from '../lib/labels'
import { formatTimeShort } from '../lib/format'
import { useTranslation } from '../i18n/I18nProvider'
import { ListSkeleton } from '../components/Skeleton'
import ErrorAlert from '../components/ErrorAlert'
import EmptyState from '../components/EmptyState'
import { EmptyFilter, EmptyReview } from '../components/EmptyIllustrations'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import { useToast } from '../components/Toast'
import { Button } from '../components/ui/Button'
import { api } from '../lib/api'
import { useDefaultWorkspace } from '../hooks/useDashboard'
import {
  useDueReviews,
  useReviewPreferences,
  useReviewStats,
  useSubmitReview,
  useSubmitReviewQuiz,
  useUndoReview,
  useSuspendedReviews,
  useUpdateReviewPreferences,
} from '../hooks/useReview'
import { StatsBar } from '../components/review/StatsBar'
import { MasterySection } from '../components/review/MasterySection'
import { TrendSection } from '../components/review/TrendSection'
import { FilterBar } from '../components/review/FilterBar'
import { SessionComplete } from '../components/review/SessionComplete'
import { ReviewSession } from '../components/review/ReviewSession'
import { DailyGoalRing } from '../components/review/DailyGoalRing'
import {
  clampGoal,
  DAILY_GOAL_DEFAULT,
  normalizeIndex,
  parseReviewSession,
  rebuildQueue,
  type PersistedReviewSession,
} from '../components/review/reviewSessionUtils'

export default function ReviewPage() {
  const { t, locale } = useTranslation()
  const { toast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const [currentIndex, setCurrentIndex] = useState(0)
  const [lastResult, setLastResult] = useState<{
    mastery_level: string
    interval_days: number
    ease_factor: number
  } | null>(null)
  const [sessionReviewed, setSessionReviewed] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [filterMastery, setFilterMastery] = useState<string | null>(null)
  const [filterType, setFilterType] = useState<string | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const [sessionQualities, setSessionQualities] = useState<number[]>([])
  const [lastMemoryId, setLastMemoryId] = useState<string | null>(null)
  const [focusMode, setFocusMode] = useState(false)
  const [prevMastery, setPrevMastery] = useState<string | null>(null)
  const [mode, setMode] = useState<'learn' | 'test'>(() => {
    try {
      return localStorage.getItem('review-mode') === 'test' ? 'test' : 'learn'
    } catch {
      return 'learn'
    }
  })
  const handleModeChange = useCallback((next: 'learn' | 'test') => {
    setMode(next)
    try {
      localStorage.setItem('review-mode', next)
    } catch {
      /* 忽略存储不可用 */
    }
  }, [])

  const [testSubMode, setTestSubMode] = useState<'cloze' | 'flip'>(() => {
    try {
      return localStorage.getItem('review-test-submode') === 'flip' ? 'flip' : 'cloze'
    } catch {
      return 'cloze'
    }
  })
  const handleTestSubModeChange = useCallback((next: 'cloze' | 'flip') => {
    setTestSubMode(next)
    try {
      localStorage.setItem('review-test-submode', next)
    } catch {
      /* 忽略存储不可用 */
    }
  }, [])

  const [elapsed, setElapsed] = useState(0)
  const [paused, setPaused] = useState(false)
  const [goal, setGoal] = useState<number>(() => {
    try {
      const saved = localStorage.getItem('review-daily-goal')
      return saved ? clampGoal(Number(saved)) : DAILY_GOAL_DEFAULT
    } catch {
      return DAILY_GOAL_DEFAULT
    }
  })
  const [results, setResults] = useState<
    Array<{ title: string; quality: number; prevMastery: string | null; newMastery: string }>
  >([])
  const restoredRef = useRef(false)

  const navigate = useNavigate()
  const { data: workspaceId } = useDefaultWorkspace()
  const { data: items = [], isLoading, error, refetch } = useDueReviews()
  const { data: stats } = useReviewStats()
  const { data: suspendedReviews = [], refetch: refetchSuspended } = useSuspendedReviews()
  const submitMutation = useSubmitReview()
  const quizMutation = useSubmitReviewQuiz()
  const undoMutation = useUndoReview()
  const { data: preferences } = useReviewPreferences()
  const updatePreferences = useUpdateReviewPreferences()
  const [showSuspended, setShowSuspended] = useState(false)
  const [actionPending, setActionPending] = useState(false)

  const handleGoalChange = useCallback(
    (next: number) => {
      const clamped = clampGoal(next)
      setGoal(clamped)
      try {
        localStorage.setItem('review-daily-goal', String(clamped))
      } catch {
        /* 忽略存储不可用 */
      }
      updatePreferences.mutate(clamped)
    },
    [updatePreferences],
  )

  const prefsSeededRef = useRef(false)
  useEffect(() => {
    if (!preferences || prefsSeededRef.current) return
    prefsSeededRef.current = true
    if (preferences.updated_at) {
      const goalFromServer = clampGoal(preferences.daily_goal)
      setGoal(goalFromServer)
      try {
        localStorage.setItem('review-daily-goal', String(goalFromServer))
      } catch {
        /* 忽略存储不可用 */
      }
      return
    }
    // 服务端首次还没有偏好文件：把本地 localStorage 目标播种到服务端
    try {
      const local = localStorage.getItem('review-daily-goal')
      if (local) {
        const localGoal = clampGoal(Number(local))
        setGoal(localGoal)
        updatePreferences.mutate(localGoal)
      }
    } catch {
      /* 忽略存储不可用 */
    }
  }, [preferences, updatePreferences])

  // 会话队列快照：进入会话时冻结顺序，提交复习后不再跟随服务端列表缩短
  const [sessionQueue, setSessionQueue] = useState<typeof items | null>(null)
  // 显式重建信号（重新开始时 +1），避免依赖 refetch 的异步完成时机
  const [queueEpoch, setQueueEpoch] = useState(0)
  const [restoreReady, setRestoreReady] = useState(false)
  const savedSessionRef = useRef<PersistedReviewSession | null>(null)
  const sessionInitializedRef = useRef(false)

  // 挂载时读取上次会话（restoredRef 保证只执行一次）。索引不在此处直接设置：
  // 等列表加载后按保存的队列 ID 重建快照，再把索引夹取到有效范围。
  useEffect(() => {
    if (restoredRef.current) return
    restoredRef.current = true
    const saved = parseReviewSession(localStorage.getItem('review-session'))
    if (saved) {
      savedSessionRef.current = saved
      setFilterMastery(saved.filterMastery)
      setFilterType(saved.filterType)
      if (saved.sessionReviewed > 0) setSessionReviewed(saved.sessionReviewed)
      if (saved.sessionQualities.length > 0) setSessionQualities(saved.sessionQualities)
    }
    setRestoreReady(true)
  }, [])

  // 会话状态变化时持久化到 localStorage，刷新/关闭页面后可续练；
  // 快照建立前不写入，避免用初始值覆盖已保存进度
  useEffect(() => {
    if (!restoreReady || !sessionInitializedRef.current) return
    if (sessionReviewed === 0 && !filterMastery && !filterType) return
    if (!sessionQueue || sessionQueue.length === 0) return
    try {
      localStorage.setItem(
        'review-session',
        JSON.stringify({
          queueIds: sessionQueue.map((item) => item.memory_id),
          currentIndex,
          sessionReviewed,
          sessionQualities,
          filterMastery,
          filterType,
        }),
      )
    } catch {
      /* 忽略写入失败（隐私模式 / 配额满） */
    }
  }, [
    sessionQueue,
    currentIndex,
    sessionReviewed,
    sessionQualities,
    filterMastery,
    filterType,
    restoreReady,
  ])

  // 筛选在客户端完成：到期列表一次取回，翻筛选条件无需再请求后端
  const filteredItems = useMemo(() => {
    let result = items
    if (filterMastery) {
      result = result.filter((item) => item.mastery_level === filterMastery)
    }
    if (filterType) {
      result = result.filter((item) => item.memory_type === filterType)
    }
    return result
  }, [items, filterMastery, filterType])

  // 快照 effect 通过 ref 读取最新筛选结果，避免把 filteredItems 放进依赖：
  // 否则窗口聚焦触发的后台刷新会重建队列，打断正在进行的会话
  const filteredItemsRef = useRef(filteredItems)
  filteredItemsRef.current = filteredItems

  // 会话展示源：快照一旦建立就不再跟随服务端列表变化
  const activeItems = sessionQueue ?? filteredItems

  // 从当前条目收集去重后的记忆类型，供筛选 pill 渲染
  const availableTypes = useMemo(() => {
    const types = new Set(items.map((item) => item.memory_type))
    return Array.from(types).sort()
  }, [items])

  // 建立/重建会话队列快照：
  // - 首次：按持久化的 queueIds 重建（缺失项自动跳过），否则用当前筛选结果
  // - 筛选变化或重新开始：用最新筛选结果重建并回到第一张
  useEffect(() => {
    if (!restoreReady || isLoading || error) return

    if (sessionInitializedRef.current) {
      // 筛选变化意味着开始一轮新的队列，本轮统计需同步清零
      setSessionQueue(filteredItemsRef.current)
      setCurrentIndex(0)
      setShowAnswer(false)
      setSessionReviewed(0)
      setSessionQualities([])
      setResults([])
      setElapsed(0)
      setLastResult(null)
      setLastMemoryId(null)
      setPrevMastery(null)
      return
    }

    sessionInitializedRef.current = true
    const saved = savedSessionRef.current
    savedSessionRef.current = null

    if (saved && saved.queueIds.length > 0) {
      const rebuilt = rebuildQueue(filteredItemsRef.current, saved.queueIds)
      if (rebuilt.length > 0) {
        setSessionQueue(rebuilt)
        setCurrentIndex(normalizeIndex(saved.currentIndex, rebuilt.length))
        return
      }
    }
    setSessionQueue(filteredItemsRef.current)
    setCurrentIndex(0)
  }, [restoreReady, isLoading, error, filterMastery, filterType, queueEpoch])

  const applyReviewOutcome = useCallback(
    (
      item: (typeof activeItems)[number],
      quality: number,
      result: { mastery_level: string; interval_days: number; ease_factor: number },
    ) => {
      setPrevMastery(item.mastery_level)
      setLastResult({
        mastery_level: result.mastery_level,
        interval_days: result.interval_days,
        ease_factor: result.ease_factor,
      })
      setLastMemoryId(item.memory_id)
      setSessionReviewed((n) => n + 1)
      setSessionQualities((prev) => [...prev, quality])
      setResults((prev) => [
        ...prev,
        {
          title: item.title,
          quality,
          prevMastery: item.mastery_level,
          newMastery: result.mastery_level,
        },
      ])
      setTimeout(() => {
        setLastResult(null)
        setLastMemoryId(null)
        setPrevMastery(null)
        setCurrentIndex((i) => i + 1)
      }, 1500)
    },
    [],
  )

  const handleRate = useCallback(
    async (quality: number) => {
      if (submitMutation.isPending || quizMutation.isPending || paused) return
      const item = activeItems[currentIndex]
      if (!item) return
      try {
        const result = await submitMutation.mutateAsync({ memoryId: item.memory_id, quality })
        applyReviewOutcome(item, quality, result)
      } catch (err) {
        toast(t.review.submitFailed, 'error')
        const status = (err as { status?: number }).status
        // 记忆已删除或状态冲突：跳过该卡，不计入完成数
        if (status === 404 || status === 409) {
          setLastResult(null)
          setLastMemoryId(null)
          setPrevMastery(null)
          setCurrentIndex((i) => i + 1)
        }
      }
    },
    [activeItems, currentIndex, submitMutation, quizMutation, toast, t, paused, applyReviewOutcome],
  )

  const handleQuizSubmit = useCallback(
    async (answers: string[]) => {
      if (submitMutation.isPending || quizMutation.isPending || paused) return
      const item = activeItems[currentIndex]
      if (!item) return
      try {
        const result = await quizMutation.mutateAsync({ memoryId: item.memory_id, answers })
        const message = result.correct
          ? t.review.quizCorrect
              .replace('{matched}', String(result.matched))
              .replace('{total}', String(result.total))
          : t.review.quizIncorrect
              .replace('{matched}', String(result.matched))
              .replace('{total}', String(result.total))
              .replace('{terms}', result.expected_terms.join('、'))
        toast(message, result.correct ? 'success' : 'warning')
        applyReviewOutcome(item, result.quality, result)
      } catch {
        toast(t.review.submitFailed, 'error')
        // 判分不可用（如该记忆无可用术语）时回退到翻面自评
        setShowAnswer(true)
      }
    },
    [activeItems, currentIndex, submitMutation, quizMutation, toast, t, paused, applyReviewOutcome],
  )

  const handleUndo = useCallback(async () => {
    if (!lastMemoryId) return
    try {
      await undoMutation.mutateAsync({ memoryId: lastMemoryId })
      toast(t.review.undoSuccess, 'success')
      setLastResult(null)
      setLastMemoryId(null)
      setSessionReviewed((n) => Math.max(0, n - 1))
      setSessionQualities((prev) => prev.slice(0, -1))
      setResults((prev) => prev.slice(0, -1))
    } catch {
      toast(t.review.undoFailed, 'error')
    }
  }, [lastMemoryId, undoMutation, toast, t])

  const handleSkip = useCallback(() => {
    if (
      paused ||
      submitMutation.isPending ||
      lastResult ||
      activeItems.length === 0 ||
      currentIndex >= activeItems.length
    )
      return
    setCurrentIndex((i) => i + 1)
  }, [lastResult, activeItems.length, currentIndex, submitMutation.isPending, paused])

  // 从首页带 ?id= 跳转过来时定位到指定条目，随后清掉参数避免刷新重复定位
  const targetId = searchParams.get('id') ?? null
  useEffect(() => {
    if (!targetId || activeItems.length === 0) return
    const idx = activeItems.findIndex((item) => item.memory_id === targetId)
    if (idx >= 0) {
      setCurrentIndex(idx)
      const next = new URLSearchParams(searchParams)
      next.delete('id')
      setSearchParams(next, { replace: true })
    }
  }, [targetId, activeItems]) // eslint-disable-line react-hooks/exhaustive-deps

  // 键盘快捷键：0-5 打分、空格/回车翻面、F 切换专注、ESC 退出专注
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

      // ESC 退出专注模式
      if (e.key === 'Escape' && focusMode) {
        e.preventDefault()
        setFocusMode(false)
        return
      }

      // F 切换专注模式（打分结果展示期间不响应）
      if (e.key === 'f' || e.key === 'F') {
        if (!lastResult && !(e.target instanceof HTMLInputElement)) {
          e.preventDefault()
          setFocusMode((v) => !v)
          return
        }
      }

      if (lastResult || activeItems.length === 0 || currentIndex >= activeItems.length) return
      const key = e.key
      // P 暂停/继续
      if (key === 'p' || key === 'P') {
        e.preventDefault()
        setPaused((v) => !v)
        return
      }
      if (paused) return
      // 学习模式内容常显，无需翻面；仅测试模式响应空格/回车
      if (mode === 'test' && !showAnswer && (key === ' ' || key === 'Enter')) {
        e.preventDefault()
        setShowAnswer(true)
        return
      }
      if (key === 's' || key === 'S') {
        e.preventDefault()
        handleSkip()
        return
      }
      if ((mode === 'learn' || showAnswer) && key >= '0' && key <= '5') {
        e.preventDefault()
        handleRate(parseInt(key, 10))
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [
    lastResult,
    activeItems,
    currentIndex,
    handleRate,
    handleSkip,
    showAnswer,
    focusMode,
    mode,
    paused,
  ])

  // 切到下一张卡时重置翻面状态
  useEffect(() => {
    setShowAnswer(false)
  }, [currentIndex])

  const currentItem = activeItems[currentIndex]
  const allDone =
    !isLoading && !error && activeItems.length > 0 && currentIndex >= activeItems.length
  const noItems = !isLoading && !error && activeItems.length === 0
  const hasActiveFilters = filterMastery !== null || filterType !== null
  const progressPct =
    activeItems.length > 0 ? Math.min((currentIndex / activeItems.length) * 100, 100) : 0
  const sessionAvgQuality =
    sessionQualities.length > 0
      ? sessionQualities.reduce((a, b) => a + b, 0) / sessionQualities.length
      : null
  const sessionGoodRate =
    sessionQualities.length > 0
      ? Math.round((sessionQualities.filter((q) => q >= 3).length / sessionQualities.length) * 100)
      : null
  // 当前连续答对次数（quality >= 3 记为答对）
  const sessionStreak = useMemo(() => {
    let count = 0
    for (let i = sessionQualities.length - 1; i >= 0; i--) {
      if (sessionQualities[i] >= 3) count++
      else break
    }
    return count
  }, [sessionQualities])

  // 计时：有当前卡片且未暂停/未完成时每秒累加
  useEffect(() => {
    if (paused || allDone || noItems || !currentItem) return
    const id = window.setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => window.clearInterval(id)
  }, [paused, allDone, noItems, currentItem])

  const handleEdit = useCallback(
    (memoryId: string) => {
      navigate(`/memories?memoryId=${memoryId}`)
    },
    [navigate],
  )

  const handleSuspend = useCallback(
    async (memoryId: string) => {
      setActionPending(true)
      try {
        await api.suspendReview(memoryId, workspaceId ?? undefined)
        toast(t.review.suspendSuccess, 'success')
        refetchSuspended()
        refetch()
        setCurrentIndex((i) => i + 1)
      } catch {
        toast(t.review.actionFailed, 'error')
      } finally {
        setActionPending(false)
      }
    },
    [workspaceId, toast, t, refetchSuspended, refetch],
  )

  const handleReset = useCallback(
    async (memoryId: string) => {
      setActionPending(true)
      try {
        await api.resetReview(memoryId, workspaceId ?? undefined)
        toast(t.review.resetSuccess, 'success')
        refetch()
      } catch {
        toast(t.review.actionFailed, 'error')
      } finally {
        setActionPending(false)
      }
    },
    [workspaceId, toast, t, refetch],
  )

  const handleResume = useCallback(
    async (memoryId: string) => {
      setActionPending(true)
      try {
        await api.resumeReview(memoryId, workspaceId ?? undefined)
        toast(t.review.resumeSuccess, 'success')
        refetchSuspended()
        refetch()
      } catch {
        toast(t.review.actionFailed, 'error')
      } finally {
        setActionPending(false)
      }
    },
    [workspaceId, toast, t, refetchSuspended, refetch],
  )

  const clearSession = useCallback(async () => {
    setCurrentIndex(0)
    setLastResult(null)
    setLastMemoryId(null)
    setPrevMastery(null)
    setSessionQualities([])
    setSessionReviewed(0)
    setFocusMode(false)
    setElapsed(0)
    setPaused(false)
    setResults([])
    setSessionQueue(null)
    sessionInitializedRef.current = false
    try {
      localStorage.removeItem('review-session')
    } catch {
      /* 忽略存储不可用 */
    }
    try {
      await refetch()
    } finally {
      // 等最新列表就绪后再重建快照
      setQueueEpoch((v) => v + 1)
    }
  }, [refetch])

  return (
    <PageShell
      maxWidth="max-w-6xl"
      contentWidth="max-w-4xl"
      header={<PageTitle icon={<Brain size={18} />} title={t.review.title} />}
    >
      {isLoading ? (
        <ListSkeleton rows={3} />
      ) : error ? (
        <ErrorAlert
          message={t.review.loadFailed}
          onRetry={() => refetch()}
          retryLabel={t.common.retry}
        />
      ) : (
        <>
          {/* 每日目标 */}
          {stats && (
            <DailyGoalRing
              done={stats.reviewed_today ?? 0}
              streakDays={stats.streak_days ?? 0}
              goal={goal}
              onChange={handleGoalChange}
              quizAccuracy={stats.quiz_accuracy}
              quizAttempts={stats.quiz_attempts ?? 0}
            />
          )}

          {/* 统计条 */}
          {stats && (
            <StatsBar
              dueNow={stats.due_now}
              dueToday={stats.due_today}
              reviewedToday={stats.reviewed_today}
              totalScheduled={stats.total_scheduled}
              sessionReviewed={sessionReviewed}
            />
          )}

          {/* 掌握度分布 */}
          {stats && (
            <MasterySection
              distribution={stats.mastery_distribution}
              total={stats.total_scheduled}
            />
          )}

          {/* 复习趋势 */}
          {stats?.review_trend && <TrendSection data={stats.review_trend} />}

          {/* 筛选栏 */}
          <FilterBar
            itemCount={items.length}
            filterMastery={filterMastery}
            filterType={filterType}
            setFilterMastery={setFilterMastery}
            setFilterType={setFilterType}
            showFilters={showFilters}
            setShowFilters={setShowFilters}
            hasActiveFilters={hasActiveFilters}
            availableTypes={availableTypes}
          />

          {/* 已暂停的复习 */}
          {suspendedReviews.length > 0 && (
            <div className="mb-4">
              <button
                type="button"
                onClick={() => setShowSuspended((v) => !v)}
                className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-secondary)]"
              >
                {t.review.suspendedList.replace('{n}', String(suspendedReviews.length))}
                {showSuspended ? (
                  <ChevronUp size={13} aria-hidden="true" />
                ) : (
                  <ChevronDown size={13} aria-hidden="true" />
                )}
              </button>
              {showSuspended && (
                <div className="mt-2 space-y-1.5">
                  {suspendedReviews.map((item) => (
                    <div
                      key={item.memory_id}
                      className="flex items-center gap-2 rounded-lg border border-[var(--border-default)] bg-surface-elevated/30 px-3 py-2"
                    >
                      <span
                        className={`shrink-0 rounded-lg border px-1.5 py-0.5 text-xs ${TYPE_COLORS[item.memory_type] ?? 'border-[var(--border-default)] bg-surface-inset text-[var(--text-secondary)]'}`}
                      >
                        {typeLabel(t.common, item.memory_type)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm text-[var(--text-secondary)]">
                        {item.title}
                      </span>
                      {item.suspended_at && (
                        <span className="shrink-0 text-[10px] text-[var(--text-tertiary)]">
                          {formatTimeShort(item.suspended_at, locale)}
                        </span>
                      )}
                      <Button
                        size="xs"
                        variant="ghost"
                        disabled={actionPending}
                        onClick={() => handleResume(item.memory_id)}
                      >
                        {t.review.resumeReview}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 无到期条目 */}
          {noItems && !hasActiveFilters && (
            <EmptyState
              illustration={<EmptyReview />}
              message={`${t.review.allCaughtUp} — ${t.review.noDueDescription}`}
            />
          )}

          {/* 被筛选条件过滤空 */}
          {noItems && hasActiveFilters && items.length > 0 && (
            <EmptyState illustration={<EmptyFilter />} message={t.review.noMatchFilter} />
          )}

          {/* 全部完成 */}
          {allDone && (
            <SessionComplete
              sessionReviewed={sessionReviewed}
              sessionAvgQuality={sessionAvgQuality}
              sessionGoodRate={sessionGoodRate}
              sessionStreak={sessionStreak}
              clearSession={clearSession}
              results={results}
              elapsedSec={elapsed}
              goal={goal}
              t={t}
            />
          )}

          {/* 复习卡片 */}
          {currentItem && !allDone && (
            <ReviewSession
              currentItem={currentItem}
              showAnswer={showAnswer}
              setShowAnswer={setShowAnswer}
              lastResult={lastResult}
              prevMastery={prevMastery}
              sessionStreak={sessionStreak}
              currentIndex={currentIndex}
              totalItems={activeItems.length}
              progressPct={progressPct}
              focusMode={focusMode}
              setFocusMode={setFocusMode}
              handleSkip={handleSkip}
              handleRate={handleRate}
              onQuizSubmit={handleQuizSubmit}
              quizPending={quizMutation.isPending}
              handleUndo={handleUndo}
              isPending={submitMutation.isPending}
              undoPending={undoMutation.isPending}
              onEdit={handleEdit}
              onSuspend={handleSuspend}
              onReset={handleReset}
              actionPending={actionPending}
              locale={locale}
              t={t}
              mode={mode}
              onModeChange={handleModeChange}
              testSubMode={testSubMode}
              onTestSubModeChange={handleTestSubModeChange}
              elapsed={elapsed}
              paused={paused}
              onTogglePause={() => setPaused((v) => !v)}
            />
          )}
        </>
      )}
    </PageShell>
  )
}
