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

export function useSuspendedReviews() {
  const { data: workspaceId } = useDefaultWorkspace()
  return useQuery({
    queryKey: ['suspendedReviews', workspaceId],
    queryFn: () => api.getSuspendedReviews(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 2 * 60 * 1000,
  })
}

export function useReviewPreferences() {
  return useQuery({
    queryKey: ['reviewPreferences'],
    queryFn: () => api.getReviewPreferences(),
    staleTime: 5 * 60 * 1000,
  })
}

export function useUpdateReviewPreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (dailyGoal: number) => api.updateReviewPreferences(dailyGoal),
    onSuccess: (data) => {
      queryClient.setQueryData(['reviewPreferences'], data)
    },
  })
}

export function useSubmitReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ memoryId, quality }: { memoryId: string; quality: number }) =>
      api.submitReview(memoryId, quality),
    onSuccess: () => {
      // 只刷新统计。到期列表由复习页维护冻结快照：提交后立即失效会让服务端列表
      // 缩短，而本地索引同时推进，导致跳过下一张卡。列表在会话结束时统一刷新。
      queryClient.invalidateQueries({ queryKey: ['reviewStats'] })
    },
  })
}

export function useSubmitReviewQuiz() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ memoryId, answers }: { memoryId: string; answers: string[] }) =>
      api.submitReviewQuiz(memoryId, answers),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviewStats'] })
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
    },
  })
}
