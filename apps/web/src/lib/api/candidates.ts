import { request } from './base'
import type { PaginatedResponse } from './base'
import type { Candidate } from './types'

export const getCandidates = (opts?: {
  workspaceId?: string
  type?: string
  title?: string
  status?: string
  limit?: number
  offset?: number
}) => {
  const params = new URLSearchParams()
  const status = opts?.status ?? 'pending_review'
  if (status !== 'all') params.set('status', status)
  if (opts?.workspaceId) params.set('workspace_id', opts.workspaceId)
  if (opts?.type) params.set('type', opts.type)
  if (opts?.title) params.set('title', opts.title)
  if (opts?.limit) params.set('limit', String(opts.limit))
  if (opts?.offset) params.set('offset', String(opts.offset))
  return request<PaginatedResponse<Candidate>>(`/candidates?${params.toString()}`)
}

export const getCandidate = (id: string) => request<Candidate>(`/candidates/${id}`)

export const createCandidate = (body: {
  workspace_id: string
  title: string
  content: string
  type: string
  source?: string
  client_write_id?: string
}) =>
  request<{ candidate: Candidate; similar_items: unknown[]; hint: string | null }>('/candidates', {
    method: 'POST',
    body: JSON.stringify(body),
  })

/** 撤销自动生效：归档生成的正式记忆并留痕，候选保持 approved；
 *  候选不存在或无 auto_approve 审核记录时后端返回 404 */
export const revertAutoApprove = (id: string) =>
  request<Candidate>(`/candidates/${id}/revert-auto-approve`, { method: 'POST' })
