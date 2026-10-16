import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ConfigData, HealthResponse } from '../lib/api'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () =>
      api.getHealth().catch((): HealthResponse => ({
        status: 'error',
        database: 'unknown',
        version: 'unknown',
      })),
    // 轮询由 useNetworkStatus 驱动（10s 间隔），本 hook 复用同一 ['health']
    // 查询缓存供设置页展示，避免同一端点两份缓存各自轮询
    staleTime: 10_000,
  })
}

export function useConfig() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['config'],
    queryFn: () => api.getConfig(),
    staleTime: 5 * 60 * 1000,
  })
  const mutation = useMutation({
    mutationFn: (body: Partial<ConfigData>) => api.patchConfig(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] })
    },
  })
  return { ...query, patchConfig: mutation }
}
