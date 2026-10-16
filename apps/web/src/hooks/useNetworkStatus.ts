import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

/**
 * 返回 API 服务是否可达。
 *
 * 复用 TanStack Query 的 ['health'] 共享缓存（与 SettingsPage 的 useHealth
 * 同一端点），而非另起轮询循环；浏览器 online/offline 事件仍会触发即时复查。
 */
export function useNetworkStatus() {
  const queryClient = useQueryClient()
  const { isSuccess, isError, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.getHealth(),
    staleTime: 10_000,
    refetchInterval: 10_000,
    retry: false,
  })

  useEffect(() => {
    const handleOnline = () => {
      refetch()
    }
    const handleOffline = () => {
      // 断网瞬间立即失效 health 缓存，让 UI 马上感知，不等下个轮询周期
      queryClient.invalidateQueries({ queryKey: ['health'] })
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [refetch, queryClient])

  // 判定离线：查询失败，或浏览器报告离线
  if (!navigator.onLine) return false
  if (isError) return false
  return isSuccess
}
