import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useConflicts(limit = 50) {
  return useQuery({
    queryKey: ['conflicts', limit],
    queryFn: () => api.getConflicts(limit),
    staleTime: 60_000,
  })
}

export function useResolveConflict() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, resolution }: { id: string; resolution: string }) =>
      api.resolveConflict(id, resolution),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conflicts'] })
    },
  })
}
