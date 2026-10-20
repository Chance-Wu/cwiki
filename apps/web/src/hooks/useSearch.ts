import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api } from '../lib/api'

export type SearchMode = 'text' | 'semantic' | 'hybrid'

export interface SearchResult {
  id?: string
  title: string
  content: string
  type: string
  score?: number | null
  similarity_score?: number | null
}

export interface SearchResponse {
  results: SearchResult[]
  total: number
  insufficient?: boolean
}

// 类型过滤在结果级应用：后端返回的 type 为空时按 'fact' 兜底归类
function filterByType(results: SearchResult[], memoryType?: string): SearchResult[] {
  if (!memoryType) return results
  return results.filter((r) => (r.type || 'fact') === memoryType)
}

// 三种检索模式的分页策略不同：hybrid 走后端分页（服务端排序 + offset）；
// semantic / BM25 一次取回 50 条，类型过滤与分页都在前端完成
async function executeSearch(
  query: string,
  mode: SearchMode,
  opts: { memoryType?: string; limit: number; offset: number },
): Promise<SearchResponse> {
  if (mode === 'semantic') {
    const data = await api.semanticSearch(query, 50)
    // semantic 端点的相似度字段为 similarity_score，归一化为 score 供结果行统一展示
    const results = filterByType(data.results || [], opts.memoryType).map((r) => ({
      ...r,
      score: r.score ?? r.similarity_score ?? null,
    }))
    return { results, total: results.length }
  }
  if (mode === 'hybrid') {
    const wsId = await api.getDefaultWorkspaceId()
    if (!wsId) throw new Error('No workspace')
    const data = await api.hybridSearch(query, wsId, {
      memory_type: opts.memoryType,
      limit: opts.limit,
      offset: opts.offset,
    })
    const results = data.results || []
    return { results, total: data.total ?? results.length }
  }
  const data = await api.searchBM25(query, 50)
  const results = filterByType(data.results || [], opts.memoryType)
  return { results, total: results.length }
}

export function useSearch(
  query: string,
  mode: SearchMode,
  opts?: { memoryType?: string; page?: number; pageSize?: number },
) {
  const memoryType = opts?.memoryType || undefined
  const page = opts?.page ?? 1
  const pageSize = opts?.pageSize ?? 10
  const serverPaginated = mode === 'hybrid'
  return useQuery({
    // 前端分页模式下 page/pageSize 固定写入 0，保证同一查询只占一份缓存
    queryKey: [
      'search',
      query,
      mode,
      memoryType ?? null,
      serverPaginated ? page : 0,
      serverPaginated ? pageSize : 0,
    ],
    queryFn: () =>
      executeSearch(query, mode, {
        memoryType,
        limit: serverPaginated ? pageSize : 0,
        offset: serverPaginated ? (page - 1) * pageSize : 0,
      }),
    enabled: query.trim().length > 0,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  })
}
