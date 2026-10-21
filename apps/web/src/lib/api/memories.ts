import { request } from './base'
import type { PaginatedResponse } from './base'
import type {
  FileMemory,
  Memory,
  SearchResult,
  VersionCommit,
  MemoryVersion,
  OptimizeResult,
  Lifecycle,
  Relation,
  RelatedMemory,
  MergeSuggestion,
  MergeHistoryItem,
} from './types'

// --- File Memories CRUD ---

// /v1/memories 列表项：DB 视图，在 FileMemory 形状上补充 workspace_id（UUID）与效用分。
// utility_score 为 null 表示聚合降级未算出（区别于算出为 0 的合法分）。
// 响应实际不含 file_path/created/updated 等文件视图字段（打开详情时经 getMemoryDetail
// 合并补全），类型保持 FileMemory 兼容以免影响既有调用方（如 CandidateMergeModal）
export type MemoryListItem = FileMemory & {
  workspace_id: string | null
  utility_score: number | null
}

// 列表页渲染记录：列表项与搜索结果（纯 FileMemory）的公共形状，效用分可选
export type MemoryListRecord = FileMemory & { utility_score?: number | null }

// 列表走 /v1/memories（DB 视图）：支持 workspace_id/type/status 过滤，响应含
// utility_score 与 last_used_at；与 /v1/file-memories（文件视图）共享同一批 id，
// status 合法值为 active | archived，不传则不过滤（含全部状态）
export const getMemories = (opts?: {
  workspace_id?: string
  type?: string
  status?: string
  tags?: string[]
  limit?: number
  offset?: number
}) => {
  const params = new URLSearchParams()
  if (opts?.workspace_id) params.set('workspace_id', opts.workspace_id)
  if (opts?.type) params.set('type', opts.type)
  if (opts?.status) params.set('status', opts.status)
  if (opts?.tags?.length) params.set('tags', opts.tags.join(','))
  if (opts?.limit) params.set('limit', String(opts.limit))
  if (opts?.offset) params.set('offset', String(opts.offset))
  const qs = params.toString()
  return request<PaginatedResponse<MemoryListItem>>(`/memories${qs ? `?${qs}` : ''}`)
}

export const getMemoryStats = () =>
  request<{
    file_count: number
    vector_count: number
    vector_index_path: string
    git_commits: number
    has_changes: boolean
    type_distribution: Record<string, number>
  }>('/file-memories/stats')

export const getMemoryDetail = (id: string) => request<FileMemory>(`/file-memories/${id}`)

export const createMemory = (body: {
  title: string
  content: string
  type: string
  tags?: string[]
  related?: string[]
}) => request<FileMemory>('/file-memories', { method: 'POST', body: JSON.stringify(body) })

export const updateMemory = (
  memoryId: string,
  body: { title?: string; content?: string; type?: string; tags?: string[]; related?: string[] },
) =>
  request<FileMemory>(`/file-memories/${memoryId}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })

export const deleteMemory = (memoryId: string) =>
  request<{ message: string }>(`/file-memories/${memoryId}`, { method: 'DELETE' })

export const batchDeleteMemories = (ids: string[]) =>
  request<{ deleted: string[]; failed: { id: string; error: string }[] }>(
    '/file-memories/batch-delete',
    { method: 'POST', body: JSON.stringify({ ids }) },
  )

export const rebuildIndex = () =>
  request<{ message: string; indexed_count: number; vector_count: number }>(
    '/file-memories/rebuild-index',
    { method: 'POST' },
  )

// --- Search ---

export const searchBM25 = (q: string, limit = 50) =>
  request<{ results: FileMemory[]; total: number }>(
    `/file-memories/search/query?q=${encodeURIComponent(q)}&limit=${limit}`,
  )

export const hybridSearch = (
  query: string,
  workspaceId: string,
  opts?: { memory_type?: string; limit?: number; offset?: number },
) =>
  request<{ results: SearchResult[]; total: number; query: string; insufficient?: boolean }>(
    '/search',
    {
      method: 'POST',
      body: JSON.stringify({
        keyword: query,
        workspace_id: workspaceId,
        limit: 20,
        offset: 0,
        // 最低向量相似度门槛：拦截乱码/无关查询的凑数结果
        threshold: 0.3,
        ...opts,
      }),
    },
  )

export const semanticSearch = (query: string, limit = 10) =>
  request<{ results: FileMemory[]; total: number }>('/file-memories/search/semantic', {
    method: 'POST',
    // 最低余弦相似度门槛：完全无关的记忆不再返回高分凑数
    body: JSON.stringify({ keyword: query, limit, threshold: 0.3 }),
  })

// --- Versions ---

export const getVersions = (limit = 20) =>
  request<{ commits: VersionCommit[]; total: number }>(`/file-memories/versions?limit=${limit}`)

export const getMemoryVersions = (memoryId: string, limit = 20) =>
  request<MemoryVersion[]>(`/memories/${memoryId}/versions?limit=${limit}`)

// --- DB Memories (optimize / update / lifecycle / relations) ---

export const optimizeMemory = (memoryId: string) =>
  request<OptimizeResult>(`/memories/${memoryId}/optimize`, { method: 'POST' })

export const applyMemoryUpdate = (
  memoryId: string,
  body: {
    title?: string
    content?: string
    reason?: string
    status?: string
    confidence?: number
    importance?: number
  },
) => request<Memory>(`/memories/${memoryId}`, { method: 'PATCH', body: JSON.stringify(body) })

export const getMemoryLifecycle = (memoryId: string) =>
  request<Lifecycle>(`/memories/${memoryId}/lifecycle`)

export const getMemoryRelations = (memoryId: string, depth = 1) =>
  request<{
    memory_id: string
    relations: Relation[]
    related_memories: RelatedMemory[]
    total_relations: number
  }>(`/memories/${memoryId}/relations?depth=${depth}`)

export const createMemoryRelation = (
  memoryId: string,
  targetMemoryId: string,
  relationType: string,
  confidence = 1.0,
) =>
  request<Relation>(`/memories/${memoryId}/relations`, {
    method: 'POST',
    body: JSON.stringify({
      target_memory_id: targetMemoryId,
      relation_type: relationType,
      confidence,
    }),
  })

export const deleteMemoryRelation = (memoryId: string, relationId: string) =>
  request<{ status: string; id: string }>(`/memories/${memoryId}/relations/${relationId}`, {
    method: 'DELETE',
  })

export const updateMemoryRelation = (
  memoryId: string,
  relationId: string,
  patch: { relation_type?: string; confidence?: number },
) =>
  request<Relation>(`/memories/${memoryId}/relations/${relationId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })

export const getMergeSuggestions = (workspaceId: string, limit = 10) =>
  request<{
    items: MergeSuggestion[]
    total: number
    generated_at: string | null
    strategy?: string
  }>(`/memories/merge-suggestions?workspace_id=${workspaceId}&limit=${limit}`)

export const getMergeHistory = (workspaceId: string, limit = 20, offset = 0) =>
  request<{
    items: MergeHistoryItem[]
    total: number
    limit: number
    offset: number
  }>(`/memories/merge-history?workspace_id=${workspaceId}&limit=${limit}&offset=${offset}`)

export const triggerConsolidate = () =>
  request<{ status: string; message: string }>(`/memories/consolidate`, {
    method: 'POST',
  })

export const mergeMemories = (
  sourceId: string,
  targetId: string,
  mergedContent: string,
  similarity?: number,
  strategy?: string,
) =>
  request<{ merged_memory_id: string; archived_memory_id: string }>(`/memories/merge`, {
    method: 'POST',
    body: JSON.stringify({
      source_memory_id: sourceId,
      target_memory_id: targetId,
      merged_content: mergedContent,
      similarity,
      strategy,
    }),
  })

// --- Tags ---

export interface TagInfo {
  name: string
  count: number
}

export const listTags = (workspaceId?: string) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<{ tags: TagInfo[]; total: number }>(`/tags${qs ? `?${qs}` : ''}`)
}

export const updateMemoryTags = (memoryId: string, tags: string[]) =>
  request<Memory>(`/memories/${memoryId}`, {
    method: 'PATCH',
    body: JSON.stringify({ tags }),
  })

export const renameTag = (tagName: string, newName: string, workspaceId?: string) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<{ old_name: string; new_name: string; updated_count: number }>(
    `/tags/${encodeURIComponent(tagName)}${qs ? `?${qs}` : ''}`,
    {
      method: 'PUT',
      body: JSON.stringify({ new_name: newName }),
    },
  )
}

export const mergeTags = (sourceTags: string[], targetTag: string, workspaceId?: string) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<{ source_tags: string[]; target_tag: string; updated_count: number }>(
    `/tags/merge${qs ? `?${qs}` : ''}`,
    {
      method: 'POST',
      body: JSON.stringify({ source_tags: sourceTags, target_tag: targetTag }),
    },
  )
}

export const deleteTag = (tagName: string, workspaceId?: string) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<{ tag: string; updated_count: number }>(
    `/tags/${encodeURIComponent(tagName)}${qs ? `?${qs}` : ''}`,
    { method: 'DELETE' },
  )
}

// --- 详情增强（P2-F2）：来源证据 / 反馈明细 / 检索命中历史 ---

/** 来源证据条目（GET /v1/memories/{id} 的 evidence 数组元素） */
export interface MemoryEvidenceItem {
  id: string
  source_type: string
  source_ref: string | null
  content: string | null
  created_at: string
}

/** 反馈明细条目（GET /v1/memories/{id}/feedback 的 items 元素） */
export interface MemoryFeedbackItem {
  id: string
  feedback_type: string
  source_type: string
  source_id: string | null
  reason: string | null
  created_at: string
}

export interface MemoryFeedbackDetailResponse {
  memory_id: string
  total: number
  items: MemoryFeedbackItem[]
}

/** 单次检索命中明细（signals/filter_reasons 取自 trace metadata，可能为空） */
export interface MemoryRetrievalHitItem {
  trace_id: string
  query: string
  retrieved_at: string
  rank: number | null
  score: number | null
  used: boolean
  signals: Record<string, number>
  filter_reasons: { memory_id?: string; stage: string; reason: string }[]
}

export interface MemoryRetrievalHistoryResponse {
  memory_id: string
  total: number
  items: MemoryRetrievalHitItem[]
}

// 原生详情端点：/v1/memories/{id} 同时返回 memory/versions/evidence，
// 列表页数据（file-memories）已覆盖 memory 展示，这里只消费 evidence
export const getMemoryNativeDetail = (memoryId: string) =>
  request<{ evidence: MemoryEvidenceItem[] }>(`/memories/${memoryId}`)

export const getMemoryFeedbackDetail = (memoryId: string, limit = 50) =>
  request<MemoryFeedbackDetailResponse>(`/memories/${memoryId}/feedback?limit=${limit}`)

// limit 上限 20（后端约束），total 为命中总次数，供"加载更多"判断
export const getMemoryRetrievalHistory = (memoryId: string, limit = 5) =>
  request<MemoryRetrievalHistoryResponse>(`/memories/${memoryId}/retrieval-history?limit=${limit}`)
