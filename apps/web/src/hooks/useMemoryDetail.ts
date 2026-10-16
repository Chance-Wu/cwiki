import { useState, useEffect, useCallback } from 'react'
import {
  getMemoryNativeDetail,
  getMemoryFeedbackDetail,
  getMemoryRetrievalHistory,
  type MemoryEvidenceItem,
  type MemoryFeedbackDetailResponse,
  type MemoryRetrievalHistoryResponse,
} from '../lib/api/memories'

// 详情弹窗子模块共享的加载态结构：error 只区分成败，细节由调用方决定重试 UI
interface DetailLoadState<T> {
  data: T | null
  loading: boolean
  error: boolean
  reload: () => void
}

function useDetailLoad<T>(fetcher: () => Promise<T>, deps: unknown[]): DetailLoadState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  // fetcher 由 useCallback 保证引用稳定，deps 为其闭包依赖
  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      setData(await fetcher())
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    load()
  }, [load])

  return { data, loading, error, reload: load }
}

/** 来源证据：必须走原生详情端点 /v1/memories/{id}（file-memories 端点不返回 evidence） */
export function useMemoryEvidence(memoryId: string): DetailLoadState<MemoryEvidenceItem[]> {
  return useDetailLoad<MemoryEvidenceItem[]>(async () => {
    const detail = await getMemoryNativeDetail(memoryId)
    return detail.evidence ?? []
  }, [memoryId])
}

/** 反馈明细列表（含 human/agent/auto 来源标记），后端按时间倒序、默认 50 条 */
export function useMemoryFeedbackDetail(
  memoryId: string,
): DetailLoadState<MemoryFeedbackDetailResponse> {
  return useDetailLoad<MemoryFeedbackDetailResponse>(
    () => getMemoryFeedbackDetail(memoryId),
    [memoryId],
  )
}

/** 检索命中历史：limit 递增触发 refetch 实现"加载更多"（后端上限 20） */
export function useMemoryRetrievalHistory(
  memoryId: string,
  limit: number,
): DetailLoadState<MemoryRetrievalHistoryResponse> {
  return useDetailLoad<MemoryRetrievalHistoryResponse>(
    () => getMemoryRetrievalHistory(memoryId, limit),
    [memoryId, limit],
  )
}
