import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ConfigData, HealthResponse, WriteDecisionData, WritePolicyData } from '../lib/api'

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

export function useWritePolicy() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['write-policy'],
    queryFn: () => api.getWritePolicy(),
    staleTime: 5 * 60 * 1000,
  })
  const mutation = useMutation({
    mutationFn: (body: Pick<WritePolicyData, 'enabled' | 'rules'>) => api.updateWritePolicy(body),
    onSuccess: (data) => {
      queryClient.setQueryData(['write-policy'], data)
      // 策略保存后 settings 已即时重载，配置页的其他字段无需刷新；
      // 但清理缓存避免后续打开配置页读到旧策略快照
      queryClient.invalidateQueries({ queryKey: ['config'] })
    },
  })
  return { ...query, update: mutation }
}

export function useWriteDecision() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['write-decisions'],
    queryFn: () => api.getWriteDecisions(),
    staleTime: 5 * 60 * 1000,
  })
  const mutation = useMutation({
    mutationFn: (body: Pick<WriteDecisionData, 'enabled' | 'default_action' | 'rules'>) =>
      api.updateWriteDecisions(body),
    onSuccess: (data) => {
      queryClient.setQueryData(['write-decisions'], data)
      queryClient.invalidateQueries({ queryKey: ['config'] })
    },
  })
  return { ...query, update: mutation }
}
