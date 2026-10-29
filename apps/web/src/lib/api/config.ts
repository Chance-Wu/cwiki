import { request } from './base'
import type {
  ConfigData,
  IntegrityReport,
  ConfigPatchResult,
  WriteDecisionData,
  WriteDecisionPreview,
  WriteDecisionPreviewRequest,
  WritePolicyData,
} from './types'

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

export const previewWriteDecisions = (body: WriteDecisionPreviewRequest) =>
  request<WriteDecisionPreview>('/config/write-decisions/preview', {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const restartService = () =>
  request<{ restarting: boolean; message: string }>('/system/restart', { method: 'POST' })

export const getSystemIntegrity = () => request<IntegrityReport>('/system/integrity')
