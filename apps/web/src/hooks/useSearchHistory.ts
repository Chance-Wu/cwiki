import { useState, useCallback } from 'react'

// 搜索历史：新词条置顶并去重，超过上限截断，状态与 localStorage 同步持久化
const STORAGE_KEY = 'cwiki:search-history'
const MAX_ITEMS = 20

function loadHistory(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveHistory(history: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(history))
}

export function useSearchHistory() {
  const [history, setHistory] = useState<string[]>(loadHistory)

  const addHistory = useCallback((query: string) => {
    const trimmed = query.trim()
    if (!trimmed) return
    setHistory((prev) => {
      const next = [trimmed, ...prev.filter((q) => q !== trimmed)].slice(0, MAX_ITEMS)
      saveHistory(next)
      return next
    })
  }, [])

  const removeHistory = useCallback((query: string) => {
    setHistory((prev) => {
      const next = prev.filter((q) => q !== query)
      saveHistory(next)
      return next
    })
  }, [])

  const clearHistory = useCallback(() => {
    setHistory([])
    saveHistory([])
  }, [])

  return { history, addHistory, removeHistory, clearHistory }
}
