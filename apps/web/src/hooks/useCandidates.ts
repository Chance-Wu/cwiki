import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { api, type Workspace } from '../lib/api'

export function useWorkspaces() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: () => api.getWorkspaces().catch(() => [] as Workspace[]),
    staleTime: 5 * 60 * 1000,
  })
}

export function useCandidates(opts?: {
  workspaceId?: string
  source?: string
  type?: string
  title?: string
  status?: string
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: ['candidates', opts],
    queryFn: () => api.getCandidates(opts),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function useReviewCandidate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      candidateId,
      action,
      body,
    }: {
      candidateId: string
      action: string
      body?: Record<string, unknown>
    }) => api.reviewCandidate(candidateId, action, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidates'] })
    },
  })
}

export function useBatchReviewCandidate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ items, action }: { items: string[]; action: string }) =>
      api.batchReview(items.map((candidate_id) => ({ candidate_id, action }))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidates'] })
    },
  })
}

// 撤销 auto-approve：归档自动生成的正式记忆，候选保持 approved 留在列表
export function useRevertAutoApprove() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (candidateId: string) => api.revertAutoApprove(candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidates'] })
    },
  })
}
