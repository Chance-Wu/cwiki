import { request } from './base'
import type {
  HealthResponse,
  MemoryStatus,
  MemoryHealth,
  LearningSuggestions,
  ConsistencyReport,
} from './types'

// --- Health / Status ---

export const getHealth = () => request<HealthResponse>('/health')

/** 四方存储一致性对账（DB/Markdown/index.db/vectors），实时只读检查，不做修复 */
export const getConsistency = () => request<ConsistencyReport>('/consistency')

export const getDashboardStats = () =>
  request<{ candidates: number; high_value: number; conflicts: number; approved: number }>(
    '/dashboard-stats',
  )

export const getMetrics = () =>
  request<{
    retrieval: {
      avg_latency_ms: number
      queries_24h: number
      success_rate: number
      total_queries: number
    }
    feedback: { useful: number; not_useful: number }
    sessions: { active: number; total: number; success_rate: number }
    storage: { vector_count: number }
  }>('/metrics')

export const getMemoryHealth = (memoryId: string) =>
  request<MemoryHealth>(`/memory-health/${memoryId}`)

export const getLearningSuggestions = (workspaceId: string) => {
  const params = new URLSearchParams({ workspace_id: workspaceId })
  return request<LearningSuggestions>(`/context/suggestions?${params.toString()}`)
}

// --- Evolution / Memory Status ---

export const getMemoryStatus = (workspaceId?: string) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<MemoryStatus>(`/memory-status${qs ? `?${qs}` : ''}`)
}

// --- Health Summary / Candidate Quality ---

export const getHealthSummary = () =>
  request<{
    total: number
    avg_score: number
    distribution: { healthy: number; needs_review: number; suspicious: number }
  }>('/health-summary')

export const getCandidateQuality = () =>
  request<{
    total: number
    avg_score: number
    distribution: { high: number; medium: number; low: number }
  }>('/candidate-quality')
