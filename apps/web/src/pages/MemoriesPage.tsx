import {
  useState,
  useEffect,
  useMemo,
  useCallback,
  lazy,
  Suspense,
  useDeferredValue,
  useRef,
} from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { spring } from '../lib/motion'
import { Plus, Loader2, RefreshCw, Database } from 'lucide-react'
import { useTranslation, translate } from '../i18n/I18nProvider'
import { api, type FileMemory, type MergeSuggestion } from '../lib/api'
import { type MemoryListItem, type MemoryListRecord } from '../lib/api/memories'
import { ensureUtc } from '../lib/format'
import { typeLabel } from '../lib/labels'
import Pagination from '../components/Pagination'
import { useToast } from '../components/Toast'
import { ListSkeleton } from '../components/Skeleton'
import ErrorAlert from '../components/ErrorAlert'
import EmptyState from '../components/EmptyState'
import { EmptyMemory } from '../components/EmptyIllustrations'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import type { SearchBoxHandle } from '../components/SearchBox'
import type { OptimizePreview } from '../components/memory/MemoryDetailModal'
import MemoryItem, { MEMORY_TYPES } from '../components/memories/MemoryItem'
import BatchActionBar from '../components/memories/BatchActionBar'
import MergeDialog from '../components/memories/MergeDialog'
import MemoriesFilterPanel from '../components/memories/MemoriesFilterPanel'
import MergeSuggestionsBanner from '../components/memories/MergeSuggestionsBanner'
import MergeHistoryPanel from '../components/memories/MergeHistoryPanel'
import MemoryListHeader from '../components/memories/MemoryListHeader'

const MemoryDetailModal = lazy(() => import('../components/memory/MemoryDetailModal'))
const MemoryCreateModal = lazy(() => import('../components/memory/MemoryCreateModal'))
const MemoryOptimizePreviewModal = lazy(
  () => import('../components/memory/MemoryOptimizePreviewModal'),
)
import HealthCard from '../components/memory/HealthCard'
import {
  useMemories,
  useWorkspacesList,
  useMemoryStats,
  useRebuildIndex,
  useApplyMemoryUpdate,
  useMergeSuggestions,
  useMergeMemories,
  useTriggerConsolidate,
} from '../hooks/useMemories'
import { useSearch, type SearchMode } from '../hooks/useSearch'
import { useSearchHistory } from '../hooks/useSearchHistory'
import { useListKeyboardNav } from '../hooks/useListKeyboardNav'
import { useBatchSelection } from '../hooks/useBatchSelection'

// 列表记录：/v1/memories 列表项（含效用分/最后使用）与搜索结果（FileMemory）的公共形状
type MemoryRecord = MemoryListRecord

// 时间范围为前端过滤（后端列表接口无 created_after 类参数），仅作用于当前页数据
const TIME_RANGE_DAYS: Record<string, number> = { '7d': 7, '30d': 30, '90d': 90 }

export default function MemoriesPage() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const typeParam = searchParams.get('type')
  const validTypeParam = typeParam && MEMORY_TYPES.includes(typeParam) ? typeParam : null
  const memoryIdParam = searchParams.get('memoryId')

  const [searchInput, setSearchInput] = useState('')
  const deferredQuery = useDeferredValue(searchInput)
  const [detailMemory, setDetailMemory] = useState<MemoryRecord | null>(null)
  const [preview, setPreview] = useState<OptimizePreview | null>(null)
  const [showCreate, setShowCreate] = useState(searchParams.get('create') === '1')
  const [typeFilter, setTypeFilter] = useState<string>(validTypeParam ?? 'all')
  // 首页工作区总览通过 ?workspace=<id> 跳转到这里预置筛选
  const [workspaceFilter, setWorkspaceFilter] = useState(searchParams.get('workspace') ?? 'all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [timeRange, setTimeRange] = useState('all')
  const [selectedTags, setSelectedTags] = useState<string[]>(
    searchParams.get('tags')?.split(',').filter(Boolean) ?? [],
  )
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [error, setError] = useState<string | null>(null)

  const [mergeTarget, setMergeTarget] = useState<MergeSuggestion | null>(null)
  const [mergedContent, setMergedContent] = useState('')
  const [mergeSourceContent, setMergeSourceContent] = useState('')
  const [mergeTargetContent, setMergeTargetContent] = useState('')
  const [mergeSourceFilePath, setMergeSourceFilePath] = useState('')
  const [mergeTargetFilePath, setMergeTargetFilePath] = useState('')
  const [mergeLoading, setMergeLoading] = useState(false)

  const [batchDeleteConfirm, setBatchDeleteConfirm] = useState(false)
  const [batchDeleteLoading, setBatchDeleteLoading] = useState(false)

  const [searchMode, setSearchMode] = useState<SearchMode>('text')
  const { history: searchHistory, addHistory, removeHistory, clearHistory } = useSearchHistory()
  const searchInputRef = useRef<SearchBoxHandle>(null)

  const isSearching = deferredQuery.trim().length > 0

  const memoriesQuery = useMemories(
    isSearching
      ? undefined
      : {
          workspace_id: workspaceFilter !== 'all' ? workspaceFilter : undefined,
          type: typeFilter !== 'all' ? typeFilter : undefined,
          status: statusFilter !== 'all' ? statusFilter : undefined,
          tags: selectedTags.length > 0 ? selectedTags : undefined,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        },
    { enabled: !isSearching },
  )
  const searchQuery = useSearch(deferredQuery.trim(), searchMode, {
    memoryType: typeFilter !== 'all' ? typeFilter : undefined,
    tags: selectedTags,
  })
  const statsQuery = useMemoryStats()
  const workspacesQuery = useWorkspacesList()

  // 标签列表：与工作区/状态筛选保持一致，并清理已不存在的已选标签
  const [tagsList, setTagsList] = useState<{ name: string; count: number }[]>([])
  const refreshTagsList = useCallback(() => {
    api
      .listTags(
        workspaceFilter !== 'all' ? workspaceFilter : undefined,
        statusFilter !== 'all' ? statusFilter : undefined,
      )
      .then((res) => {
        setTagsList(res.tags || [])
        const names = new Set((res.tags || []).map((tag) => tag.name))
        setSelectedTags((prev) => {
          const next = prev.filter((tag) => names.has(tag))
          return next.length === prev.length ? prev : next
        })
      })
      .catch(() => {})
  }, [workspaceFilter, statusFilter])
  useEffect(() => {
    refreshTagsList()
  }, [refreshTagsList])

  const handleTagsChanged = useCallback(() => {
    refreshTagsList()
    void memoriesQuery.refetch()
  }, [refreshTagsList, memoriesQuery])

  // /v1/memories 返回 workspace_id（UUID），徽标展示需要名称——用工作区列表解析；
  // 解析不到时回退到 item 自带的 workspace 字段（搜索结果走此路径）
  const wsNameById = useMemo(() => {
    const map = new Map<string, string>()
    for (const w of workspacesQuery.data ?? []) map.set(w.id, w.name)
    return map
  }, [workspacesQuery.data])

  const memories = useMemo<MemoryListItem[]>(() => {
    const items = memoriesQuery.data?.items ?? []
    return items.map((m) => ({
      ...m,
      workspace:
        (m.workspace_id ? wsNameById.get(m.workspace_id) : undefined) ?? m.workspace ?? null,
    }))
  }, [memoriesQuery.data, wsNameById])

  const total = memoriesQuery.data?.total ?? 0
  const searchResults = (searchQuery.data?.results ?? null) as FileMemory[] | null
  const isServerPaginated = isSearching && searchMode === 'hybrid'
  const loading = isSearching ? searchQuery.isLoading : memoriesQuery.isLoading

  useEffect(() => {
    if (memories.length === 0 && page > 1 && !memoriesQuery.isLoading) {
      setPage(page - 1)
    }
  }, [memories.length, page, memoriesQuery.isLoading])

  useEffect(() => {
    if (memoryIdParam) {
      api
        .getMemoryDetail(memoryIdParam)
        .then(setDetailMemory)
        .catch(() => toast(t.memories.detailLoadFailed, 'error'))
    }
  }, [memoryIdParam, toast, t.memories.detailLoadFailed])

  const rebuildMutation = useRebuildIndex()
  const applyMutation = useApplyMemoryUpdate()

  const workspaceId = memories[0]?.workspace ?? null
  const mergeSuggestionsQuery = useMergeSuggestions(workspaceId)
  const mergeSuggestions = mergeSuggestionsQuery.data?.items ?? []
  const mergeGeneratedAt = mergeSuggestionsQuery.data?.generated_at ?? null
  const mergeMutation = useMergeMemories()
  const consolidateMutation = useTriggerConsolidate()

  // 类型筛选同步到 URL query，刷新/分享链接可保留筛选状态
  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    if (typeFilter !== 'all') {
      next.set('type', typeFilter)
    } else {
      next.delete('type')
    }
    setSearchParams(next, { replace: true })
  }, [typeFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  // 标签筛选同步到 URL query，刷新/分享链接可保留筛选状态
  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    if (selectedTags.length > 0) {
      next.set('tags', selectedTags.join(','))
    } else {
      next.delete('tags')
    }
    setSearchParams(next, { replace: true })
  }, [selectedTags]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleRebuildIndex = async () => {
    try {
      const res = await rebuildMutation.mutateAsync()
      toast(
        translate(t.memories.rebuildSuccess, {
          indexed: res.indexed_count,
          vectors: res.vector_count,
        }),
        'success',
      )
    } catch {
      toast(t.memories.rebuildFailed, 'error')
    }
  }

  const handleApply = async () => {
    if (!preview) return
    try {
      await applyMutation.mutateAsync({
        memoryId: preview.memoryId,
        body: {
          title: preview.optimizedTitle,
          content: preview.optimizedContent,
          reason: 'LLM optimization',
        },
      })
      setPreview(null)
    } catch {
      setError(t.memories.optimizationFailed)
    }
  }

  const handleOpenMerge = async (s: MergeSuggestion) => {
    setMergeTarget(s)
    setMergeLoading(true)
    try {
      const [source, target] = await Promise.all([
        api.getMemoryDetail(s.source_id),
        api.getMemoryDetail(s.target_id),
      ])
      setMergeSourceContent(source.content)
      setMergeTargetContent(target.content)
      setMergeSourceFilePath(source.file_path)
      setMergeTargetFilePath(target.file_path)
      setMergedContent(target.content + '\n\n' + source.content)
    } catch {
      setMergeSourceContent(s.source_content_preview)
      setMergeTargetContent(s.target_content_preview)
      setMergeSourceFilePath('')
      setMergeTargetFilePath('')
      setMergedContent(s.target_content_preview + '\n\n' + s.source_content_preview)
    } finally {
      setMergeLoading(false)
    }
  }

  const handleMergeConfirm = async () => {
    if (!mergeTarget) return
    try {
      await mergeMutation.mutateAsync({
        sourceId: mergeTarget.source_id,
        targetId: mergeTarget.target_id,
        mergedContent,
        similarity: mergeTarget.similarity,
        strategy: mergeSuggestionsQuery.data?.strategy,
      })
      toast(t.memories.mergeSuccess, 'success')
      setMergeTarget(null)
      mergeSuggestionsQuery.refetch()
    } catch {
      toast(t.memories.mergeFailed, 'error')
    }
  }

  const openMemory = useCallback((m: MemoryRecord) => {
    // 列表项（/v1/memories DB 视图）缺 file_path/workspace 名/tags 等文件视图字段，
    // 先用列表数据立即打开弹窗，再异步拉取详情合并补全；失败时保留列表数据
    setDetailMemory(m)
    api
      .getMemoryDetail(m.id)
      .then((detail) => {
        setDetailMemory((prev) => (prev && prev.id === m.id ? { ...prev, ...detail } : prev))
      })
      .catch(() => {
        // 文件视图补全失败不影响弹窗展示
      })
  }, [])

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return
    setBatchDeleteLoading(true)
    try {
      const res = await api.batchDeleteMemories(Array.from(selectedIds))
      if (res.failed.length === 0) {
        toast(translate(t.memories.batchDeleteSuccess, { n: res.deleted.length }), 'success')
      } else {
        toast(
          translate(t.memories.batchDeletePartial, {
            success: res.deleted.length,
            failed: res.failed.length,
          }),
          'error',
        )
      }
      clearSelection()
      setBatchDeleteConfirm(false)
      memoriesQuery.refetch()
      statsQuery.refetch()
    } catch {
      toast(t.memories.batchDeleteFailed, 'error')
    } finally {
      setBatchDeleteLoading(false)
    }
  }

  const handleSearch = (q: string) => {
    if (!q.trim()) return
    addHistory(q.trim())
    setSearchInput(q)
    setPage(1)
    setFocusedIndex(-1)
    const next = new URLSearchParams(searchParams)
    next.set('q', q.trim())
    next.set('mode', searchMode)
    setSearchParams(next, { replace: true })
  }

  const statsDistribution = statsQuery.data?.type_distribution ?? null

  const typeCounts = useMemo<Record<string, number> | null>(() => {
    if (isSearching) {
      const counts: Record<string, number> = { all: (searchResults ?? []).length }
      for (const m of searchResults ?? []) {
        const tp = m.type || 'fact'
        counts[tp] = (counts[tp] || 0) + 1
      }
      return counts
    }
    if (statsDistribution) {
      const counts: Record<string, number> = {
        all: Object.values(statsDistribution).reduce((a, b) => a + b, 0),
      }
      for (const [tp, n] of Object.entries(statsDistribution)) counts[tp] = n
      return counts
    }
    return null
  }, [isSearching, searchResults, statsDistribution])

  const displayItems = useMemo(() => {
    if (!isSearching) return memories
    if (isServerPaginated) return searchResults ?? []
    return (searchResults ?? []).slice((page - 1) * pageSize, page * pageSize)
  }, [isSearching, isServerPaginated, searchResults, page, pageSize, memories])

  // 时间范围为前端过滤：仅裁剪当前页/当前结果集，分页 total 仍来自后端（UI 已注明「本页内过滤」）
  const visibleItems = useMemo(() => {
    if (timeRange === 'all') return displayItems
    const days = TIME_RANGE_DAYS[timeRange] ?? 0
    const cutoff = Date.now() - days * 86400000
    return displayItems.filter((m) => {
      const ts = m.updated_at || m.updated
      // 无时间戳的条目不裁掉，避免误伤数据
      if (!ts) return true
      return new Date(ensureUtc(ts)).getTime() >= cutoff
    })
  }, [displayItems, timeRange])

  const displayItemIds = useMemo(() => visibleItems.map((m) => m.id), [visibleItems])
  const { selectedIds, toggleSelect, toggleSelectAll, clearSelection } =
    useBatchSelection(displayItemIds)

  const modalOpen = !!(detailMemory || preview || mergeTarget || showCreate)

  const { focusedIndex, setFocusedIndex } = useListKeyboardNav({
    itemCount: visibleItems.length,
    indexAttr: 'memory-index',
    onSelect: (idx) => toggleSelect(visibleItems[idx].id),
    onOpen: (idx) => openMemory(visibleItems[idx]),
    onFocusSearch: () => searchInputRef.current?.focus(),
    disabled: modalOpen,
  })

  // setFocusedIndex 来自 useListKeyboardNav（声明于本行之后），deps 数组在渲染期求值，
  // 直接列入会触发 TDZ 错误；其底层为 useState setter、身份稳定，故豁免该依赖检查。
  useEffect(() => {
    setPage(1)
    setFocusedIndex(-1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deferredQuery, workspaceFilter, statusFilter, timeRange])

  const hasActiveFilters =
    isSearching ||
    typeFilter !== 'all' ||
    workspaceFilter !== 'all' ||
    statusFilter !== 'all' ||
    timeRange !== 'all' ||
    selectedTags.length > 0

  const clearAllFilters = () => {
    setSearchInput('')
    setTypeFilter('all')
    setWorkspaceFilter('all')
    setStatusFilter('all')
    setTimeRange('all')
    setSelectedTags([])
    setPage(1)
  }

  const titleSuggestions = useMemo<FileMemory[]>(() => {
    const q = deferredQuery.trim().toLowerCase()
    if (!q) return []
    const pool = isSearching ? (searchResults ?? []) : memories
    const out: FileMemory[] = []
    for (const m of pool) {
      if (out.length >= 5) break
      if ((m.title || '').toLowerCase().includes(q)) out.push(m)
    }
    return out
  }, [deferredQuery, isSearching, searchResults, memories])

  const displayTotal = isSearching
    ? isServerPaginated
      ? (searchQuery.data?.total ?? 0)
      : (searchResults?.length ?? 0)
    : total

  const countText = isSearching
    ? translate(t.memories.searchResultCount, { n: displayTotal })
    : typeFilter !== 'all'
      ? `${total} ${typeLabel(t.common, typeFilter)}`
      : translate(t.memories.latestMemories, { n: total })

  const emptyMessage = isSearching
    ? t.memories.noMatch
    : hasActiveFilters
      ? t.memories.noFilterResults
      : t.memories.empty

  return (
    <PageShell
      maxWidth="max-w-6xl"
      header={
        <>
          <div className="flex items-center justify-between gap-4">
            <PageTitle icon={<Database size={18} />} title={t.memories.title} />
            <div className="flex items-center gap-2">
              <HealthCard />
              <Button
                onClick={handleRebuildIndex}
                disabled={rebuildMutation.isPending}
                variant="secondary"
                className="flex items-center gap-1.5"
              >
                <RefreshCw
                  size={14}
                  className={rebuildMutation.isPending ? 'animate-spin' : ''}
                  aria-hidden="true"
                />
                <span className="hidden sm:inline">
                  {rebuildMutation.isPending ? t.common.rebuilding : t.common.rebuildIndex}
                </span>
              </Button>
              <Button
                onClick={() => memoriesQuery.refetch()}
                disabled={loading}
                variant="secondary"
                className="flex items-center gap-1.5"
              >
                <Loader2 size={14} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
                <span className="hidden sm:inline">
                  {loading ? t.common.loading : t.common.refresh}
                </span>
              </Button>
              <Button onClick={() => setShowCreate(true)} className="flex items-center gap-1.5">
                <Plus size={15} aria-hidden="true" />
                {t.memories.create}
              </Button>
            </div>
          </div>
        </>
      }
    >
      {/* 搜索与筛选面板 */}
      <MemoriesFilterPanel
        searchInput={searchInput}
        onSearchInputChange={setSearchInput}
        searchInputRef={searchInputRef}
        onSearchSubmit={handleSearch}
        searchHistory={searchHistory}
        titleSuggestions={titleSuggestions}
        onRemoveHistory={removeHistory}
        onClearHistory={clearHistory}
        searchFetching={searchQuery.isFetching}
        searchError={!!searchQuery.isError}
        searchMode={searchMode}
        onSearchModeChange={setSearchMode}
        typeCounts={typeCounts}
        typeFilter={typeFilter}
        onTypeFilterChange={(v) => {
          setTypeFilter(v)
          setPage(1)
          setFocusedIndex(-1)
        }}
        workspaces={workspacesQuery.data ?? []}
        workspaceFilter={workspaceFilter}
        onWorkspaceFilterChange={setWorkspaceFilter}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        timeRange={timeRange}
        onTimeRangeChange={setTimeRange}
        tagsList={tagsList}
        onTagsChanged={handleTagsChanged}
        selectedTags={selectedTags}
        onSelectedTagsChange={(tags) => {
          setSelectedTags(tags)
          setPage(1)
        }}
      />

      {/* 合并建议横幅 */}
      <MergeSuggestionsBanner
        suggestions={mergeSuggestions}
        generatedAt={mergeGeneratedAt}
        consolidatePending={consolidateMutation.isPending}
        strategy={mergeSuggestionsQuery.data?.strategy}
        onConsolidate={() => consolidateMutation.mutate()}
        onOpenMerge={handleOpenMerge}
        onBatchMerge={async (selected) => {
          // 批量合并：拉取全文后依次执行每个合并，跟踪进度与成功/失败数
          let successCount = 0
          let failCount = 0
          for (let i = 0; i < selected.length; i++) {
            const s = selected[i]
            try {
              // 拉取全文（与单条合并一致），失败时降级用 preview
              let mergedContent: string
              try {
                const [sourceDetail, targetDetail] = await Promise.all([
                  api.getMemoryDetail(s.source_id),
                  api.getMemoryDetail(s.target_id),
                ])
                mergedContent = targetDetail.content + '\n\n' + sourceDetail.content
              } catch {
                mergedContent = s.target_content_preview + '\n\n' + s.source_content_preview
              }
              await mergeMutation.mutateAsync({
                sourceId: s.source_id,
                targetId: s.target_id,
                mergedContent,
                similarity: s.similarity,
                strategy: mergeSuggestionsQuery.data?.strategy,
              })
              successCount++
            } catch (err) {
              failCount++
              console.error('Batch merge failed for pair:', s, err)
            }
          }
          mergeSuggestionsQuery.refetch()
          if (failCount === 0) {
            toast(t.memories.batchMergeComplete.replace('{n}', String(successCount)), 'success')
          } else {
            toast(
              t.memories.batchMergePartial
                .replace('{success}', String(successCount))
                .replace('{total}', String(selected.length))
                .replace('{failed}', String(failCount)),
              'error',
            )
          }
        }}
      />

      {/* 合并历史 */}
      {workspaceId && (
        <div className="mb-5">
          <MergeHistoryPanel workspaceId={workspaceId} />
        </div>
      )}

      {error && (
        <ErrorAlert
          message={error}
          className="mb-4"
          onDismiss={() => setError(null)}
          dismissLabel={t.memories.dismiss}
        />
      )}

      {/* 区块标题 */}
      <MemoryListHeader
        countText={countText}
        visibleCount={visibleItems.length}
        selectedCount={selectedIds.size}
        onToggleAll={toggleSelectAll}
        showClear={hasActiveFilters}
        onClear={() => {
          clearAllFilters()
          clearSelection()
        }}
      />

      {/* 批量操作栏 */}
      {selectedIds.size > 0 && (
        <BatchActionBar
          selectedCount={selectedIds.size}
          batchDeleteConfirm={batchDeleteConfirm}
          batchDeleteLoading={batchDeleteLoading}
          onCancel={() => {
            if (batchDeleteConfirm) setBatchDeleteConfirm(false)
            else clearSelection()
          }}
          onDeleteClick={() => setBatchDeleteConfirm(true)}
          onBatchDelete={handleBatchDelete}
        />
      )}

      {loading && memories.length === 0 && !isSearching ? (
        <ListSkeleton rows={5} />
      ) : displayItems.length === 0 ? (
        <EmptyState
          illustration={<EmptyMemory />}
          message={emptyMessage}
          description={hasActiveFilters ? t.memories.noFilterResultsDesc : undefined}
          action={
            hasActiveFilters ? (
              <Button variant="secondary" size="sm" onClick={clearAllFilters}>
                {t.memories.clearFilters}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Card className="divide-y divide-[var(--border-default)] overflow-hidden">
          <AnimatePresence initial={false}>
            {visibleItems.map((m, idx) => (
              <motion.div
                key={m.id}
                layout
                // 不加 layoutId：列表行没有共享布局的配对对象（标题→弹窗共享动画走
                // mem-title-{id}），挂行级 layoutId 只会让 AnimatePresence 退出路径更脆弱
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ type: 'spring', ...spring.layout }}
              >
                <MemoryItem
                  memory={m}
                  idx={idx}
                  selected={selectedIds.has(m.id)}
                  focused={idx === focusedIndex}
                  query={deferredQuery}
                  onToggle={toggleSelect}
                  onOpen={openMemory}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        </Card>
      )}

      {/* 分页 */}
      <Pagination
        total={displayTotal}
        page={page}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={(s) => {
          setPageSize(s)
          setPage(1)
        }}
      />

      {/* 详情弹窗 */}
      <Suspense fallback={null}>
        <MemoryDetailModal
          memory={detailMemory}
          onClose={() => setDetailMemory(null)}
          onMemoryUpdated={handleTagsChanged}
          onNavigateToMemory={async (id) => {
            try {
              const mem = await api.getMemoryDetail(id)
              setDetailMemory(mem)
            } catch {
              toast(t.memories.detailLoadFailed, 'error')
            }
          }}
        />
      </Suspense>

      {/* 优化预览弹窗 */}
      <Suspense fallback={null}>
        <MemoryOptimizePreviewModal
          preview={preview}
          applying={applyMutation.isPending}
          onClose={() => setPreview(null)}
          onApply={handleApply}
        />
      </Suspense>

      {/* 新建记忆弹窗 */}
      <Suspense fallback={null}>
        <MemoryCreateModal
          open={showCreate}
          onClose={() => setShowCreate(false)}
          onCreated={() => memoriesQuery.refetch()}
          defaultType={validTypeParam ?? undefined}
        />
      </Suspense>

      {/* 合并确认弹窗 */}
      <MergeDialog
        mergeTarget={mergeTarget}
        mergedContent={mergedContent}
        mergeSourceContent={mergeSourceContent}
        mergeTargetContent={mergeTargetContent}
        mergeSourceFilePath={mergeSourceFilePath}
        mergeTargetFilePath={mergeTargetFilePath}
        mergeLoading={mergeLoading}
        mergeMutationPending={mergeMutation.isPending}
        onClose={() => setMergeTarget(null)}
        onMergedChange={setMergedContent}
        onConfirm={handleMergeConfirm}
      />
    </PageShell>
  )
}
