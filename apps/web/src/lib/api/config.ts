import { request } from './base'
import type { ConfigData, ConfigPatchResult } from './types'

export const getConfig = () => request<ConfigData>('/config')

export const patchConfig = (body: Partial<ConfigData>) =>
  request<ConfigPatchResult>('/config', { method: 'PATCH', body: JSON.stringify(body) })

export const restartService = () =>
  request<{ restarting: boolean; message: string }>('/system/restart', { method: 'POST' })
