import { useState, useCallback, useEffect } from 'react'

/**
 * 列表页共享的多选批量操作状态。
 *
 * @param itemIds 当前页条目 ID 列表；该数组变化时（翻页 / 筛选 / 搜索）
 *                自动清空选中，避免把上一页的选择带进下一批操作。
 */
export function useBatchSelection(itemIds: string[]) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // 可见条目集合变化（翻页 / 筛选 / 搜索）时清空选中，防止跨页误操作
  useEffect(() => {
    setSelectedIds(new Set())
  }, [itemIds])

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (prev.size === itemIds.length && itemIds.length > 0) {
        return new Set()
      }
      return new Set(itemIds)
    })
  }, [itemIds])

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  const removeSelected = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }, [])

  return { selectedIds, toggleSelect, toggleSelectAll, clearSelection, removeSelected }
}
