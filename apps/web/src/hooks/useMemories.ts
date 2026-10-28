import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useMemories(
  opts?: {
    workspace_id?: string
    type?: string
    status?: string
    tags?: string[]
    limit?: number
    offset?: number
    min_confidence?: number
    max_confidence?: number
    min_importance?: number
    max_importance?: number
    usage?: 'unused' | 'low' | 'medium' | 'high'
    decay?: 'fresh' | 'aging' | 'stale'
  },
  queryOpts?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: ['memories', opts],
    queryFn: () => api.getMemories(opts),
    enabled: queryOpts?.enabled,
    staleTime: 30_000,
  })
}

// 筛选器下拉用的工作区列表；staleTime 放长，工作区变更频率低
export function useWorkspacesList() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: () => api.getWorkspaces(),
    staleTime: 5 * 60_000,
  })
}

export function useMemoryStats() {
  return useQuery({
    queryKey: ['memory-stats'],
    queryFn: () => api.getMemoryStats(),
    staleTime: 60_000,
  })
}

export function useHealthSummary() {
  return useQuery({
    queryKey: ['health-summary'],
    queryFn: () => api.getHealthSummary(),
    staleTime: 60_000,
  })
}

export function useCandidateQuality() {
  return useQuery({
    queryKey: ['candidate-quality'],
    queryFn: () => api.getCandidateQuality(),
    staleTime: 60_000,
  })
}

export function useRebuildIndex() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => api.rebuildIndex(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] })
    },
  })
}

export function useApplyMemoryUpdate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      memoryId,
      body,
    }: {
      memoryId: string
      body: { title?: string; content?: string; reason?: string; status?: string }
    }) => api.applyMemoryUpdate(memoryId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] })
    },
  })
}

export function useMergeSuggestions(workspaceId: string | null) {
  return useQuery({
    queryKey: ['merge-suggestions', workspaceId],
    queryFn: () => api.getMergeSuggestions(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 60_000,
  })
}

export function useMergeMemories() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      sourceId,
      targetId,
      mergedContent,
      similarity,
      strategy,
    }: {
      sourceId: string
      targetId: string
      mergedContent: string
      similarity?: number
      strategy?: string
    }) => api.mergeMemories(sourceId, targetId, mergedContent, similarity, strategy),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] })
      queryClient.invalidateQueries({ queryKey: ['merge-suggestions'] })
      queryClient.invalidateQueries({ queryKey: ['merge-history'] })
    },
  })
}

export function useTriggerConsolidate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => api.triggerConsolidate(),
    onSuccess: () => {
      // 整理是异步任务，延迟失效合并建议缓存，等任务落库后再重新拉取
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['merge-suggestions'] })
      }, 2000)
    },
  })
}
