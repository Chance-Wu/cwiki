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
  request<{
    candidates: number
    high_value: number
    conflicts: number
    approved: number
    pending_notes: number
  }>('/dashboard-stats')

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
    distribution: { healthy: number; needs_review: number; suspicious: number; conflicted: number }
  }>('/health-summary')

export const getCandidateQuality = () =>
  request<{
    total: number
    avg_score: number
    distribution: { high: number; medium: number; low: number }
  }>('/candidate-quality')

// --- Knowledge Graph ---

export const getKnowledgeGraph = (workspaceId: string, limit = 200) => {
  const params = new URLSearchParams({ workspace_id: workspaceId, limit: String(limit) })
  return request<{
    nodes: Array<{
      id: string
      title: string
      type: string
      confidence: number
      importance: number
      degree: number
      is_isolated: boolean
    }>
    edges: Array<{
      id: string
      source: string
      target: string
      type: string
      confidence: number
      strength: number
    }>
    total_nodes: number
    total_edges: number
  }>(`/graph?${params.toString()}`)
}

// --- Quality Distribution ---

export const getQualityDistribution = (workspaceId: string) => {
  const params = new URLSearchParams({ workspace_id: workspaceId })
  return request<{
    total: number
    confidence_distribution: { low: number; medium: number; high: number }
    importance_distribution: { low: number; medium: number; high: number }
    usage_distribution: { unused: number; low: number; medium: number; high: number }
    decay_distribution: { fresh: number; aging: number; stale: number }
    averages: { confidence: number; importance: number; usage_count: number }
  }>(`/quality-distribution?${params.toString()}`)
}
