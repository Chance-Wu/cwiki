import { request } from './base'
import type { ConfigData, ConfigPatchResult, WriteDecisionData, WritePolicyData } from './types'

export const getConfig = () => request<ConfigData>('/config')

export const patchConfig = (body: Partial<ConfigData>) =>
  request<ConfigPatchResult>('/config', { method: 'PATCH', body: JSON.stringify(body) })

export const getWritePolicy = () => request<WritePolicyData>('/config/write-policy')

export const updateWritePolicy = (body: Pick<WritePolicyData, 'enabled' | 'rules'>) =>
  request<WritePolicyData>('/config/write-policy', {
    method: 'PUT',
    body: JSON.stringify(body),
  })

export const getWriteDecisions = () => request<WriteDecisionData>('/config/write-decisions')

export const updateWriteDecisions = (
  body: Pick<WriteDecisionData, 'enabled' | 'default_action' | 'rules'>,
) =>
  request<WriteDecisionData>('/config/write-decisions', {
    method: 'PUT',
    body: JSON.stringify(body),
  })

export const restartService = () =>
  request<{ restarting: boolean; message: string }>('/system/restart', { method: 'POST' })
