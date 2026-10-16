import { useState, useEffect, useCallback } from 'react'

export interface UseListKeyboardNavOptions {
  /** 列表条目总数 */
  itemCount: number
  /** 用于定位条目并滚动到可见区的 data-* 属性名（不含 "data-" 前缀） */
  indexAttr: string
  /** 聚焦条目上按下空格时触发 */
  onSelect?: (index: number) => void
  /** 聚焦条目上按下回车时触发 */
  onOpen?: (index: number) => void
  /** 按下 "/" 时触发（如聚焦搜索框） */
  onFocusSearch?: () => void
  /** 为 true 时抑制键盘导航（如弹窗打开时） */
  disabled?: boolean
  /** 为 false 时完全不挂载键盘监听 */
  enabled?: boolean
}

export function useListKeyboardNav({
  itemCount,
  indexAttr,
  onSelect,
  onOpen,
  onFocusSearch,
  disabled = false,
  enabled = true,
}: UseListKeyboardNavOptions) {
  const [focusedIndex, setFocusedIndex] = useState(-1)

  // 聚焦项变化时滚动到可见区域（nearest 避免页面跳动）
  useEffect(() => {
    if (focusedIndex >= 0) {
      const el = document.querySelector(`[data-${indexAttr}="${focusedIndex}"]`)
      el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [focusedIndex, indexAttr])

  const handleSelect = useCallback((index: number) => onSelect?.(index), [onSelect])

  const handleOpen = useCallback((index: number) => onOpen?.(index), [onOpen])

  useEffect(() => {
    if (!enabled) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (disabled) return

      if (e.key === '/' && onFocusSearch) {
        e.preventDefault()
        onFocusSearch()
      } else if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusedIndex((prev) => Math.min(prev + 1, itemCount - 1))
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        setFocusedIndex((prev) => Math.max(prev - 1, 0))
      } else if (e.key === ' ' && focusedIndex >= 0 && focusedIndex < itemCount) {
        e.preventDefault()
        handleSelect(focusedIndex)
      } else if (e.key === 'Enter' && focusedIndex >= 0 && focusedIndex < itemCount) {
        e.preventDefault()
        handleOpen(focusedIndex)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [itemCount, focusedIndex, disabled, enabled, onFocusSearch, handleSelect, handleOpen])

  return { focusedIndex, setFocusedIndex } as const
}
