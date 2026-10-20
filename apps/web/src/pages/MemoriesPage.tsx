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
import { spring, ease, duration } from '../lib/motion'
import {
  Plus,
  Merge,
  X,
  Loader2,
  RefreshCw,
  AlertCircle,
  Database,
  Tag,
  Folder,
  ListFilter,
  Clock,
  Tags,
  Pencil,
} from 'lucide-react'
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
import { Checkbox } from '../components/ui/Checkbox'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { Select } from '../components/ui/Select'
import SearchBox, { type SearchBoxHandle } from '../components/SearchBox'
import type { OptimizePreview } from '../components/memory/MemoryDetailModal'
import MemoryItem, { MEMORY_TYPES } from '../components/memories/MemoryItem'
import BatchActionBar from '../components/memories/BatchActionBar'
import MergeDialog from '../components/memories/MergeDialog'
import TagManagePanel from '../components/memory/TagManagePanel'

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
  const [workspaceFilter, setWorkspaceFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [timeRange, setTimeRange] = useState('all')
  const [selectedTags, setSelectedTags] = useState<string[]>(
    searchParams.get('tags')?.split(',').filter(Boolean) ?? [],
  )
  const [showAllTags, setShowAllTags] = useState(false)
  const [showTagManage, setShowTagManage] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [error, setError] = useState<string | null>(null)

  const [showMergeSuggestions, setShowMergeSuggestions] = useState(true)
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
  })
  const statsQuery = useMemoryStats()
  const workspacesQuery = useWorkspacesList()

  // 标签列表
  const [tagsList, setTagsList] = useState<{ name: string; count: number }[]>([])
  useEffect(() => {
    api.listTags().then((res) => setTagsList(res.tags || [])).catch(() => {})
  }, [])

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

  // setFocusedIndex 来自 useListKeyboardNav（声明于本行之后），deps 数组在渲染期求值，
  // 直接列入会触发 TDZ 错误；其底层为 useState setter、身份稳定，故豁免该依赖检查。
  // 查询词或任一筛选变化都回到第一页，避免停留在越界页码上
  useEffect(() => {
    setPage(1)
    setFocusedIndex(-1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deferredQuery, workspaceFilter, statusFilter, timeRange])

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
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: duration.modal, ease: ease.out }}
        className="mb-5"
      >
        {/* 搜索框 */}
        <div className="mb-3">
          <SearchBox
            ref={searchInputRef}
            value={searchInput}
            onChange={setSearchInput}
            onSubmit={handleSearch}
            loading={searchQuery.isFetching}
            history={searchHistory}
            suggestions={titleSuggestions}
            onRemoveHistory={removeHistory}
            onClearHistory={clearHistory}
          />
          {isSearching && searchQuery.isError && !searchQuery.isFetching && (
            <div className="mt-2 flex items-center gap-1.5 text-sm text-danger-fg" role="alert">
              <AlertCircle size={14} strokeWidth={1.5} aria-hidden="true" />
              <span>{t.search.searchFailed}</span>
            </div>
          )}
        </div>

        {/* 检索模式与类型筛选行 */}
        <div className="flex flex-col sm:flex-row gap-2.5">
          {/* 检索模式切换 */}
          <SegmentedControl
            value={searchMode}
            onChange={setSearchMode}
            options={[
              { value: 'text', label: t.search.modeText },
              { value: 'semantic', label: t.search.modeSemantic },
              { value: 'hybrid', label: t.search.modeHybrid },
            ]}
          />

          {/* 类型筛选下拉 */}
          <Select
            options={[
              { value: 'all', label: `${t.memories.allTypes} (${typeCounts?.all ?? 0})` },
              ...MEMORY_TYPES.filter(
                (type) => typeCounts === null || (typeCounts[type] ?? 0) > 0,
              ).map((type) => ({
                value: type,
                label: `${typeLabel(t.common, type)} (${typeCounts?.[type] ?? 0})`,
              })),
            ]}
            value={typeFilter}
            onChange={(v) => {
              setTypeFilter(v)
              setPage(1)
              setFocusedIndex(-1)
            }}
            icon={<Tag size={14} />}
          />
        </div>

        {/* 工作区 / 状态 / 时间范围筛选行。工作区与状态由后端过滤；
            后端列表接口无时间参数，时间范围仅前端过滤当前页数据 */}
        <div className="flex flex-col sm:flex-row gap-2.5 sm:items-center mt-2.5">
          <Select
            options={[
              { value: 'all', label: t.memories.allWorkspaces },
              ...(workspacesQuery.data ?? []).map((w) => ({ value: w.id, label: w.name })),
            ]}
            value={workspaceFilter}
            onChange={setWorkspaceFilter}
            icon={<Folder size={14} />}
          />
          <Select
            options={[
              { value: 'all', label: t.memories.allStatus },
              { value: 'active', label: t.memories.statusActive },
              { value: 'archived', label: t.memories.statusArchived },
            ]}
            value={statusFilter}
            onChange={setStatusFilter}
            icon={<ListFilter size={14} />}
          />
          <Select
            options={[
              { value: 'all', label: t.memories.allTime },
              { value: '7d', label: t.memories.last7Days },
              { value: '30d', label: t.memories.last30Days },
              { value: '90d', label: t.memories.last90Days },
            ]}
            value={timeRange}
            onChange={setTimeRange}
            icon={<Clock size={14} />}
          />
          {timeRange !== 'all' && (
            <span className="text-xs text-[var(--text-tertiary)]">{t.memories.pageOnlyFilter}</span>
          )}
        </div>

        {/* 标签筛选行：只显示计数≥2 的热门标签，最多 8 个，其余折叠 */}
        {tagsList.length > 0 && (() => {
          const hotTags = tagsList.filter(t => t.count >= 2).slice(0, 8)
          const coldTags = tagsList.filter(t => t.count < 2 || !hotTags.includes(t))
          const showMore = hotTags.length < tagsList.length && !showAllTags
          const displayTags = showAllTags ? tagsList.filter(t => t.count >= 2) : hotTags
          return (
            <>
            <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
              <Tags size={14} className="text-[var(--text-tertiary)] shrink-0" />
              <button
                onClick={() => {
                  setSelectedTags([])
                  setPage(1)
                }}
                className={`px-2 py-0.5 text-xs rounded-full border transition-colors flex items-center gap-1 ${
                  selectedTags.length === 0
                    ? 'bg-brand-500 text-white border-brand-500'
                    : 'bg-surface-inset text-[var(--text-secondary)] border-[var(--border-default)] hover:bg-brand-badge-bg'
                }`}
              >
                {selectedTags.length > 0 ? (
                  <>
                    <X size={10} className="opacity-70" />
                    <span>{t.memories.tagClear} {selectedTags.length}</span>
                  </>
                ) : (
                  <>
                    {t.memories.tagAll}
                    {displayTags.length > 0 && (
                      <span className="opacity-60">{displayTags.length}</span>
                    )}
                  </>
                )}
              </button>
              {displayTags.map((tag) => (
                <button
                  key={tag.name}
                  onClick={() => {
                    setSelectedTags((prev) =>
                      prev.includes(tag.name)
                        ? prev.filter((t) => t !== tag.name)
                        : [...prev, tag.name],
                    )
                    setPage(1)
                  }}
                  className={`px-2 py-0.5 text-xs rounded-full border transition-colors flex items-center gap-1 ${
                    selectedTags.includes(tag.name)
                      ? 'bg-brand-500 text-white border-brand-500'
                      : 'bg-surface-inset text-[var(--text-secondary)] border-[var(--border-default)] hover:bg-brand-badge-bg'
                  }`}
                >
                  {selectedTags.includes(tag.name) && (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  )}
                  {tag.name}
                  <span className="opacity-60 tabular-nums">{tag.count > 99 ? '99+' : tag.count}</span>
                </button>
              ))}
              {showMore && (
                <button
                  onClick={() => setShowAllTags(true)}
                  className="px-2 py-0.5 text-xs rounded-full border border-dashed border-[var(--border-default)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:border-[var(--text-tertiary)] transition-colors"
                >
                  +{coldTags.length} {t.memories.tagMore}
                </button>
              )}
              {showAllTags && hotTags.length > 8 && (
                <button
                  onClick={() => setShowAllTags(false)}
                  className="px-2 py-0.5 text-xs rounded-full border border-dashed border-[var(--border-default)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:border-[var(--text-tertiary)] transition-colors"
                >
                  {t.memories.tagCollapse}
                </button>
              )}
              <div className="flex-1" />
              <button
                onClick={() => setShowTagManage(!showTagManage)}
                className={`px-2 py-0.5 text-xs rounded-full border transition-colors flex items-center gap-1 ${
                  showTagManage
                    ? 'bg-brand-500 text-white border-brand-500'
                    : 'bg-surface-inset text-[var(--text-secondary)] border-[var(--border-default)] hover:bg-brand-badge-bg'
                }`}
              >
                <Pencil size={10} />
                {t.memories.tagManage}
              </button>
            </div>
            {showTagManage && (
              <div className="mt-2">
                <TagManagePanel
                  tags={tagsList}
                  onTagsChanged={() => {
                    api.listTags().then((res) => setTagsList(res.tags || [])).catch(() => {})
                  }}
                  onClose={() => setShowTagManage(false)}
                />
              </div>
            )}
            </>
          )
        })()}
      </motion.div>

      {/* 合并建议横幅 */}
      {showMergeSuggestions && mergeSuggestions.length > 0 && (
        <div className="mb-5 p-4 bg-warning-bg border border-warning-border rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Merge size={14} className="text-warning-fg" aria-hidden="true" />
              <span className="text-xs font-semibold text-warning-fg">
                {t.memories.mergeSuggestions}
              </span>
              <span className="text-xs font-medium text-warning-fg">
                {t.memories.mergeSuggestionsDesc}
              </span>
              {mergeGeneratedAt && (
                <span className="text-xs text-warning-fg">
                  {new Date(mergeGeneratedAt).toLocaleString()}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                onClick={() => consolidateMutation.mutate()}
                disabled={consolidateMutation.isPending}
                variant="warning"
                size="xs"
              >
                <Loader2
                  size={14}
                  className={consolidateMutation.isPending ? 'animate-spin' : ''}
                />
                {t.common.refresh}
              </Button>
              <Button
                onClick={() => setShowMergeSuggestions(false)}
                variant="icon"
                size="xs"
                title={t.common.close}
              >
                <X size={14} aria-hidden="true" />
              </Button>
            </div>
          </div>
          <div className="space-y-1">
            {mergeSuggestions.map((s, i) => (
              <motion.div
                key={`${s.source_id}-${s.target_id}`}
                className={`flex items-center justify-between bg-warning/8 border border-warning/15 rounded-lg px-3 py-2 hover:bg-warning/15 hover:border-warning/25 transition-all duration-150 cursor-pointer group`}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: 'spring', ...spring.gentle, delay: Math.min(i * 0.06, 0.3) }}
              >
                <div className="min-w-0 flex-1 text-xs">
                  <span className="text-[var(--text-primary)] truncate">{s.source_title}</span>
                  <span className="text-[var(--text-tertiary)] mx-1.5">→</span>
                  <span className="text-[var(--text-primary)] truncate">{s.target_title}</span>
                  <span className="ml-2 text-warning-fg tabular-nums font-medium">
                    {Math.round(s.similarity * 100)}%
                  </span>
                </div>
                <Button
                  onClick={() => handleOpenMerge(s)}
                  variant="subtle"
                  size="xs"
                  className="ml-2 shrink-0 opacity-80 group-hover:opacity-100"
                >
                  {t.memories.mergeAction}
                </Button>
              </motion.div>
            ))}
          </div>
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
      <div className="group flex items-center justify-between mb-3">
        <p className="text-xs text-[var(--text-secondary)] font-medium">
          {isSearching
            ? translate(t.memories.searchResultCount, { n: displayTotal })
            : typeFilter !== 'all'
              ? `${total} ${typeLabel(t.common, typeFilter)}`
              : translate(t.memories.latestMemories, { n: total })}
        </p>
        <div className="flex items-center gap-3">
          {visibleItems.length > 0 && (
            <>
              <div className="hidden sm:flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                  /
                </kbd>
                <span className="opacity-70">{t.memories.kbdSearch}</span>
                <span className="opacity-40 mx-0.5">·</span>
                <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                  j
                </kbd>
                <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                  k
                </kbd>
                <span className="opacity-70">{t.memories.kbdNavigate}</span>
                <span className="opacity-40 mx-0.5">·</span>
                <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                  ␣
                </kbd>
                <span className="opacity-70">{t.memories.kbdSelect}</span>
                <span className="opacity-40 mx-0.5">·</span>
                <kbd className="border border-[var(--border-default)] shadow-warm-xs px-1.5 py-0.5 bg-surface-inset rounded font-mono text-[10px]">
                  ⏎
                </kbd>
                <span className="opacity-70">{t.memories.kbdOpen}</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm text-[var(--text-secondary)] cursor-pointer select-none hover:text-[var(--text-primary)] transition-all duration-150">
                <Checkbox
                  checked={selectedIds.size === visibleItems.length && visibleItems.length > 0}
                  onCheckedChange={() => toggleSelectAll()}
                />
                <span
                  role="button"
                  tabIndex={0}
                  onClick={toggleSelectAll}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      toggleSelectAll()
                    }
                  }}
                >
                  {t.memories.selectAll}
                </span>
              </div>
            </>
          )}
          {(isSearching ||
            typeFilter !== 'all' ||
            workspaceFilter !== 'all' ||
            statusFilter !== 'all' ||
            timeRange !== 'all' ||
            selectedTags.length > 0) && (
            <Button
              onClick={() => {
                setSearchInput('')
                setTypeFilter('all')
                setWorkspaceFilter('all')
                setStatusFilter('all')
                setTimeRange('all')
                setSelectedTags([])
                setPage(1)
                clearSelection()
              }}
              variant="ghost"
              size="sm"
            >
              {t.memories.clearSearch}
            </Button>
          )}
        </div>
      </div>

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
          message={
            isSearching
              ? t.memories.noMatch
              : (typeFilter !== 'all' || workspaceFilter !== 'all' || statusFilter !== 'all' || timeRange !== 'all' || selectedTags.length > 0)
                ? t.memories.noFilterResults
                : t.memories.empty
          }
          description={
            (typeFilter !== 'all' || workspaceFilter !== 'all' || statusFilter !== 'all' || timeRange !== 'all' || selectedTags.length > 0)
              ? t.memories.noFilterResultsDesc
              : undefined
          }
          action={
            (typeFilter !== 'all' || workspaceFilter !== 'all' || statusFilter !== 'all' || timeRange !== 'all' || selectedTags.length > 0) ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setSearchInput('')
                  setTypeFilter('all')
                  setWorkspaceFilter('all')
                  setStatusFilter('all')
                  setTimeRange('all')
                  setSelectedTags([])
                  setPage(1)
                }}
              >
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
          onMemoryUpdated={() => memoriesQuery.refetch()}
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
