import { useState, type RefObject } from 'react'
import { motion } from 'framer-motion'
import { ease, duration } from '../../lib/motion'
import { Tag, Folder, ListFilter, Clock, Tags, X, Pencil, AlertCircle } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { type FileMemory } from '../../lib/api'
import { typeLabel } from '../../lib/labels'
import { SegmentedControl } from '../ui/SegmentedControl'
import { Select } from '../ui/Select'
import SearchBox, { type SearchBoxHandle } from '../SearchBox'
import TagManagePanel from '../memory/TagManagePanel'
import { MEMORY_TYPES } from './MemoryItem'
import type { SearchMode } from '../../hooks/useSearch'

interface MemoriesFilterPanelProps {
  searchInput: string
  onSearchInputChange: (v: string) => void
  searchInputRef: RefObject<SearchBoxHandle>
  onSearchSubmit: (q: string) => void
  searchHistory: string[]
  titleSuggestions: FileMemory[]
  onRemoveHistory: (q: string) => void
  onClearHistory: () => void
  searchFetching: boolean
  searchError: boolean
  searchMode: SearchMode
  onSearchModeChange: (m: SearchMode) => void
  typeCounts: Record<string, number> | null
  typeFilter: string
  onTypeFilterChange: (v: string) => void
  workspaces: { id: string; name: string }[]
  workspaceFilter: string
  onWorkspaceFilterChange: (v: string) => void
  statusFilter: string
  onStatusFilterChange: (v: string) => void
  timeRange: string
  onTimeRangeChange: (v: string) => void
  tagsList: { name: string; count: number }[]
  onTagsChanged: () => void
  selectedTags: string[]
  onSelectedTagsChange: (tags: string[]) => void
}

/** 记忆页搜索与筛选面板：搜索框、检索模式、类型/工作区/状态/时间筛选与标签行。
 * 标签展开/折叠与标签管理开关是纯 UI 状态，内聚在此。 */
export default function MemoriesFilterPanel({
  searchInput,
  onSearchInputChange,
  searchInputRef,
  onSearchSubmit,
  searchHistory,
  titleSuggestions,
  onRemoveHistory,
  onClearHistory,
  searchFetching,
  searchError,
  searchMode,
  onSearchModeChange,
  typeCounts,
  typeFilter,
  onTypeFilterChange,
  workspaces,
  workspaceFilter,
  onWorkspaceFilterChange,
  statusFilter,
  onStatusFilterChange,
  timeRange,
  onTimeRangeChange,
  tagsList,
  onTagsChanged,
  selectedTags,
  onSelectedTagsChange,
}: MemoriesFilterPanelProps) {
  const { t } = useTranslation()
  const [showAllTags, setShowAllTags] = useState(false)
  const [showTagManage, setShowTagManage] = useState(false)

  return (
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
          onChange={onSearchInputChange}
          onSubmit={onSearchSubmit}
          loading={searchFetching}
          history={searchHistory}
          suggestions={titleSuggestions}
          onRemoveHistory={onRemoveHistory}
          onClearHistory={onClearHistory}
        />
        {searchInput.trim().length > 0 && searchError && !searchFetching && (
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
          onChange={onSearchModeChange}
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
          onChange={onTypeFilterChange}
          icon={<Tag size={14} />}
        />
      </div>

      {/* 工作区 / 状态 / 时间范围筛选行。工作区与状态由后端过滤；
          后端列表接口无时间参数，时间范围仅前端过滤当前页数据 */}
      <div className="flex flex-col sm:flex-row gap-2.5 sm:items-center mt-2.5">
        <Select
          options={[
            { value: 'all', label: t.memories.allWorkspaces },
            ...workspaces.map((w) => ({ value: w.id, label: w.name })),
          ]}
          value={workspaceFilter}
          onChange={onWorkspaceFilterChange}
          icon={<Folder size={14} />}
        />
        <Select
          options={[
            { value: 'all', label: t.memories.allStatus },
            { value: 'active', label: t.memories.statusActive },
            { value: 'archived', label: t.memories.statusArchived },
          ]}
          value={statusFilter}
          onChange={onStatusFilterChange}
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
          onChange={onTimeRangeChange}
          icon={<Clock size={14} />}
        />
        {timeRange !== 'all' && (
          <span className="text-xs text-[var(--text-tertiary)]">{t.memories.pageOnlyFilter}</span>
        )}
      </div>

      {/* 标签筛选行：只显示计数≥2 的热门标签，最多 8 个，其余折叠 */}
      {tagsList.length > 0 &&
        (() => {
          const hotTags = tagsList.filter((t) => t.count >= 2).slice(0, 8)
          const coldTags = tagsList.filter((t) => t.count < 2 || !hotTags.includes(t))
          const showMore = hotTags.length < tagsList.length && !showAllTags
          const displayTags = showAllTags ? tagsList.filter((t) => t.count >= 2) : hotTags
          return (
            <>
              <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
                <Tags size={14} className="text-[var(--text-tertiary)] shrink-0" />
                <button
                  onClick={() => onSelectedTagsChange([])}
                  className={`px-2 py-0.5 text-xs rounded-full border transition-colors flex items-center gap-1 ${
                    selectedTags.length === 0
                      ? 'bg-brand-500 text-white border-brand-500'
                      : 'bg-surface-inset text-[var(--text-secondary)] border-[var(--border-default)] hover:bg-brand-badge-bg'
                  }`}
                >
                  {selectedTags.length > 0 ? (
                    <>
                      <X size={10} className="opacity-70" />
                      <span>
                        {t.memories.tagClear} {selectedTags.length}
                      </span>
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
                      onSelectedTagsChange(
                        selectedTags.includes(tag.name)
                          ? selectedTags.filter((t) => t !== tag.name)
                          : [...selectedTags, tag.name],
                      )
                    }}
                    className={`px-2 py-0.5 text-xs rounded-full border transition-colors flex items-center gap-1 ${
                      selectedTags.includes(tag.name)
                        ? 'bg-brand-500 text-white border-brand-500'
                        : 'bg-surface-inset text-[var(--text-secondary)] border-[var(--border-default)] hover:bg-brand-badge-bg'
                    }`}
                  >
                    {selectedTags.includes(tag.name) && (
                      <svg
                        width="10"
                        height="10"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="shrink-0"
                      >
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                    {tag.name}
                    <span className="opacity-60 tabular-nums">
                      {tag.count > 99 ? '99+' : tag.count}
                    </span>
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
                    onTagsChanged={onTagsChanged}
                    onClose={() => setShowTagManage(false)}
                  />
                </div>
              )}
            </>
          )
        })()}
    </motion.div>
  )
}
