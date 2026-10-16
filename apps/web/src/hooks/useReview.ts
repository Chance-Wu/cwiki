import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useDefaultWorkspace } from './useDashboard'

export function useDueReviews(limit = 50) {
  const { data: workspaceId } = useDefaultWorkspace()
  return useQuery({
    queryKey: ['dueReviews', workspaceId, limit],
    queryFn: () => api.getDueReviews({ workspaceId: workspaceId!, limit }),
    enabled: !!workspaceId,
    staleTime: 2 * 60 * 1000,
  })
}

export function useReviewStats() {
  const { data: workspaceId } = useDefaultWorkspace()
  return useQuery({
    queryKey: ['reviewStats', workspaceId],
    queryFn: () => api.getReviewStats(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 2 * 60 * 1000,
  })
}

export function useSubmitReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ memoryId, quality }: { memoryId: string; quality: number }) =>
      api.submitReview(memoryId, quality),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviewStats'] })
      queryClient.invalidateQueries({ queryKey: ['dueReviews'] })
    },
  })
}

export function useUndoReview() {
  const queryClient = useQueryClient()
  const { data: workspaceId } = useDefaultWorkspace()
  return useMutation({
    mutationFn: ({ memoryId }: { memoryId: string }) =>
      api.undoReview(memoryId, workspaceId ?? undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviewStats'] })
      queryClient.invalidateQueries({ queryKey: ['dueReviews'] })
    },
  })
}
