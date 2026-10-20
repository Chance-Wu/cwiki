import { useQuery, keepPreviousData } from '@tanstack/react-query'
import {
  api,
  type Conflict,
  type TaskQueueStatusResponse,
  type ConsistencyReport,
  type HealthResponse,
} from '../lib/api'

// 首页统计类查询统一 catch 为降级默认值（0 / 空数组 / null），
// 保证后端不可用时首页仍能完整渲染，而不是抛错白屏
export function useDashboardStats() {
  return useQuery({
    queryKey: ['dashboardStats'],
    queryFn: () =>
      api.getDashboardStats().catch(() => ({
        candidates: 0,
        high_value: 0,
        conflicts: 0,
        approved: 0,
        pending_notes: 0,
      })),
    staleTime: 60_000,
  })
}

export function useRecentConflicts(limit = 10) {
  return useQuery({
    queryKey: ['recentConflicts', limit],
    queryFn: () => api.getConflicts(limit).catch(() => [] as Conflict[]),
    staleTime: 60_000,
  })
}

export function useMetrics() {
  return useQuery({
    queryKey: ['metrics'],
    queryFn: () => api.getMetrics().catch(() => null),
    staleTime: 2 * 60 * 1000,
  })
}

export function useMemoryStatus(workspaceId?: string) {
  return useQuery({
    queryKey: ['memoryStatus', workspaceId],
    queryFn: () => api.getMemoryStatus(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 2 * 60 * 1000,
  })
}

export function useDefaultWorkspace() {
  return useQuery({
    queryKey: ['defaultWorkspace'],
    queryFn: () => api.getDefaultWorkspaceId().catch(() => undefined),
    staleTime: 10 * 60 * 1000,
  })
}

export function useLearningSuggestions(workspaceId?: string) {
  return useQuery({
    queryKey: ['learningSuggestions', workspaceId],
    queryFn: () => api.getLearningSuggestions(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 5 * 60 * 1000,
  })
}

export function useReviewStats(workspaceId?: string) {
  return useQuery({
    queryKey: ['reviewStats', workspaceId],
    queryFn: () => api.getReviewStats(workspaceId).catch(() => null),
    enabled: !!workspaceId,
    staleTime: 2 * 60 * 1000,
  })
}

// --- 系统诊断（P2-06）---
// 诊断类查询同样 catch 降级为 null：后端不可用时诊断卡片只显示加载失败，不影响首页其余区块

export function useTaskQueueStatus() {
  return useQuery({
    queryKey: ['task-queue-status'],
    queryFn: () => api.getTaskQueueStatus().catch(() => null as TaskQueueStatusResponse | null),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

export function useConsistency() {
  return useQuery({
    queryKey: ['consistency'],
    queryFn: () => api.getConsistency().catch(() => null as ConsistencyReport | null),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function useServiceHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api.getHealth().catch(() => null as HealthResponse | null),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}
