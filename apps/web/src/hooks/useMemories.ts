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
    review_status?:
      | 'due'
      | 'new'
      | 'learning'
      | 'familiar'
      | 'proficient'
      | 'mastered'
      | 'suspended'
      | 'unscheduled'
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

export function useMemoryStats(status?: string) {
  return useQuery({
    queryKey: ['memory-stats', status ?? 'all'],
    queryFn: () => api.getMemoryStats(status),
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
