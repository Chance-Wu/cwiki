import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api } from '../lib/api'

export type SearchMode = 'text' | 'semantic' | 'hybrid'

export interface SearchResult {
  id?: string
  title: string
  content: string
  type: string
  tags?: string[]
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

// 文件索引端点把 tags 序列化成 Python repr（"['a', 'b']"），这里兼容数组与字符串
export function parseTags(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.filter((tag): tag is string => typeof tag === 'string')
  }
  if (typeof raw !== 'string') return []
  const value = raw.trim()
  if (!value || value === '[]') return []
  if (value.startsWith('[')) {
    const inner = value.slice(1, -1).trim()
    if (!inner) return []
    return inner
      .split(',')
      .map((tag) => tag.trim().replace(/^['"]|['"]$/g, ''))
      .filter(Boolean)
  }
  return [value]
}

// 语义 / BM25 端点不支持标签参数，结果级按 AND 语义过滤
export function filterByTags<T extends { tags?: unknown }>(results: T[], tags?: string[]): T[] {
  if (!tags?.length) return results
  const wanted = tags.map((tag) => tag.toLowerCase())
  return results.filter((item) => {
    const owned = new Set(parseTags(item.tags).map((tag) => tag.toLowerCase()))
    return wanted.every((tag) => owned.has(tag))
  })
}

// 三种检索模式的分页策略不同：hybrid 走后端分页（服务端排序 + offset）；
// semantic / BM25 一次取回 50 条，类型过滤与分页都在前端完成
async function executeSearch(
  query: string,
  mode: SearchMode,
  opts: { memoryType?: string; tags?: string[]; limit: number; offset: number },
): Promise<SearchResponse> {
  if (mode === 'semantic') {
    const data = await api.semanticSearch(query, 50)
    // semantic 端点的相似度字段为 similarity_score，归一化为 score 供结果行统一展示
    const results = filterByTags(filterByType(data.results || [], opts.memoryType), opts.tags).map(
      (r) => ({
        ...r,
        score: r.score ?? r.similarity_score ?? null,
      }),
    )
    return { results, total: results.length }
  }
  if (mode === 'hybrid') {
    const wsId = await api.getDefaultWorkspaceId()
    if (!wsId) throw new Error('No workspace')
    const data = await api.hybridSearch(query, wsId, {
      memory_type: opts.memoryType,
      tags: opts.tags,
      limit: opts.limit,
      offset: opts.offset,
    })
    const results = data.results || []
    return { results, total: data.total ?? results.length }
  }
  const data = await api.searchBM25(query, 50)
  const results = filterByTags(filterByType(data.results || [], opts.memoryType), opts.tags)
  return { results, total: results.length }
}

export function useSearch(
  query: string,
  mode: SearchMode,
  opts?: { memoryType?: string; tags?: string[]; page?: number; pageSize?: number },
) {
  const memoryType = opts?.memoryType || undefined
  const tags = opts?.tags?.length ? opts.tags : undefined
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
      tags?.join(',') ?? null,
      serverPaginated ? page : 0,
      serverPaginated ? pageSize : 0,
    ],
    queryFn: () =>
      executeSearch(query, mode, {
        memoryType,
        tags,
        limit: serverPaginated ? pageSize : 0,
        offset: serverPaginated ? (page - 1) * pageSize : 0,
      }),
    enabled: query.trim().length > 0,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  })
}
