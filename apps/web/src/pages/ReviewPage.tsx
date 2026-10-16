import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Brain } from 'lucide-react'
import { useTranslation } from '../i18n/I18nProvider'
import { ListSkeleton } from '../components/Skeleton'
import ErrorAlert from '../components/ErrorAlert'
import EmptyState from '../components/EmptyState'
import { EmptyFilter, EmptyReview } from '../components/EmptyIllustrations'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import { useToast } from '../components/Toast'
import { useDueReviews, useReviewStats, useSubmitReview, useUndoReview } from '../hooks/useReview'
import { StatsBar } from '../components/review/StatsBar'
import { MasterySection } from '../components/review/MasterySection'
import { TrendSection } from '../components/review/TrendSection'
import { FilterBar } from '../components/review/FilterBar'
import { SessionComplete } from '../components/review/SessionComplete'
import { ReviewSession } from '../components/review/ReviewSession'

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
  const restoredRef = useRef(false)

  const { data: items = [], isLoading, error, refetch } = useDueReviews()
  const { data: stats } = useReviewStats()
  const submitMutation = useSubmitReview()
  const undoMutation = useUndoReview()

  // 挂载时从 localStorage 恢复上次会话进度（restoredRef 保证只执行一次）
  useEffect(() => {
    if (restoredRef.current) return
    restoredRef.current = true
    try {
      const saved = localStorage.getItem('review-session')
      if (!saved) return
      const data = JSON.parse(saved)
      if (data.filterMastery !== undefined) setFilterMastery(data.filterMastery)
      if (data.filterType !== undefined) setFilterType(data.filterType)
      if (data.sessionReviewed > 0) setSessionReviewed(data.sessionReviewed)
      if (data.sessionQualities?.length > 0) setSessionQualities(data.sessionQualities)
      if (data.currentIndex > 0) setCurrentIndex(data.currentIndex)
    } catch {
      /* 数据损坏时忽略，按新会话开始 */
    }
  }, [])

  // 会话状态变化时持久化到 localStorage，刷新/关闭页面后可续练；
  // 恢复完成前（restoredRef 未置位）不写入，避免用初始值覆盖已保存进度
  useEffect(() => {
    if (!restoredRef.current) return
    if (sessionReviewed === 0 && !filterMastery && !filterType) return
    try {
      localStorage.setItem(
        'review-session',
        JSON.stringify({
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
  }, [currentIndex, sessionReviewed, sessionQualities, filterMastery, filterType])

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

  // 从当前条目收集去重后的记忆类型，供筛选 pill 渲染
  const availableTypes = useMemo(() => {
    const types = new Set(items.map((item) => item.memory_type))
    return Array.from(types).sort()
  }, [items])

  // 筛选变化时回到第一张卡，避免索引越界
  useEffect(() => {
    setCurrentIndex(0)
    setShowAnswer(false)
  }, [filterMastery, filterType])

  const handleRate = useCallback(
    async (quality: number) => {
      if (submitMutation.isPending) return
      const item = filteredItems[currentIndex]
      if (!item) return
      try {
        setPrevMastery(item.mastery_level)
        const result = await submitMutation.mutateAsync({ memoryId: item.memory_id, quality })
        setLastResult({
          mastery_level: result.mastery_level,
          interval_days: result.interval_days,
          ease_factor: result.ease_factor,
        })
        setLastMemoryId(item.memory_id)
        setSessionReviewed((n) => n + 1)
        setSessionQualities((prev) => [...prev, quality])
        setTimeout(() => {
          setLastResult(null)
          setLastMemoryId(null)
          setPrevMastery(null)
          setCurrentIndex((i) => i + 1)
        }, 1500)
      } catch {
        toast(t.review.submitFailed, 'error')
      }
    },
    [filteredItems, currentIndex, submitMutation, toast, t],
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
    } catch {
      toast(t.review.undoFailed, 'error')
    }
  }, [lastMemoryId, undoMutation, toast, t])

  const handleSkip = useCallback(() => {
    if (
      submitMutation.isPending ||
      lastResult ||
      filteredItems.length === 0 ||
      currentIndex >= filteredItems.length
    )
      return
    setCurrentIndex((i) => i + 1)
  }, [lastResult, filteredItems.length, currentIndex, submitMutation.isPending])

  // 从首页带 ?id= 跳转过来时定位到指定条目，随后清掉参数避免刷新重复定位
  const targetId = searchParams.get('id') ?? null
  useEffect(() => {
    if (!targetId || filteredItems.length === 0) return
    const idx = filteredItems.findIndex((item) => item.memory_id === targetId)
    if (idx >= 0) {
      setCurrentIndex(idx)
      const next = new URLSearchParams(searchParams)
      next.delete('id')
      setSearchParams(next, { replace: true })
    }
  }, [targetId, filteredItems]) // eslint-disable-line react-hooks/exhaustive-deps

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

      if (lastResult || filteredItems.length === 0 || currentIndex >= filteredItems.length) return
      const key = e.key
      if (!showAnswer && (key === ' ' || key === 'Enter')) {
        e.preventDefault()
        setShowAnswer(true)
        return
      }
      if (key === 's' || key === 'S') {
        e.preventDefault()
        handleSkip()
        return
      }
      if (showAnswer && key >= '0' && key <= '5') {
        e.preventDefault()
        handleRate(parseInt(key, 10))
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [lastResult, filteredItems, currentIndex, handleRate, handleSkip, showAnswer, focusMode])

  // 切到下一张卡时重置翻面状态
  useEffect(() => {
    setShowAnswer(false)
  }, [currentIndex])

  const currentItem = filteredItems[currentIndex]
  const allDone =
    !isLoading && !error && filteredItems.length > 0 && currentIndex >= filteredItems.length
  const noItems = !isLoading && !error && filteredItems.length === 0
  const hasActiveFilters = filterMastery !== null || filterType !== null
  const progressPct =
    filteredItems.length > 0 ? Math.min((currentIndex / filteredItems.length) * 100, 100) : 0
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

  const clearSession = useCallback(() => {
    setCurrentIndex(0)
    setLastResult(null)
    setLastMemoryId(null)
    setPrevMastery(null)
    setSessionQualities([])
    setSessionReviewed(0)
    setFocusMode(false)
    try {
      localStorage.removeItem('review-session')
    } catch {
      /* 忽略存储不可用 */
    }
    refetch()
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
              totalItems={filteredItems.length}
              progressPct={progressPct}
              focusMode={focusMode}
              setFocusMode={setFocusMode}
              handleSkip={handleSkip}
              handleRate={handleRate}
              handleUndo={handleUndo}
              isPending={submitMutation.isPending}
              undoPending={undoMutation.isPending}
              locale={locale}
              t={t}
            />
          )}
        </>
      )}
    </PageShell>
  )
}
