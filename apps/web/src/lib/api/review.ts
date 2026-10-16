import { request } from './base'
import type { Review, Conflict, Feedback, ReviewItem, ReviewResult, ReviewStats } from './types'

// --- Candidate Reviews ---

export const reviewCandidate = (
  candidateId: string,
  action: string,
  body?: Record<string, unknown>,
) =>
  request<Review>('/reviews', {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId, action, reviewer_type: 'human', ...body }),
  })

export const batchReview = (items: { candidate_id: string; action: string; reason?: string }[]) =>
  request<{
    results: {
      candidate_id: string
      success: boolean
      action: string
      error?: string
      review_id?: string
    }[]
    total: number
    succeeded: number
    failed: number
  }>('/reviews/batch', {
    method: 'POST',
    body: JSON.stringify({ items, reviewer_type: 'human' }),
  })

// --- Conflicts ---

export const getConflicts = (limit = 10) => request<Conflict[]>(`/conflicts/all?limit=${limit}`)

export const resolveConflict = (id: string, resolution: string) =>
  request<Conflict>(`/conflicts/${id}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ resolution }),
  })

// --- Feedback ---

export const createFeedback = (body: {
  workspace_id: string
  memory_id: string
  feedback_type: string
  source_type?: string
  reason?: string
}) => request<Feedback>('/feedback', { method: 'POST', body: JSON.stringify(body) })

export const getFeedbackSummary = (memoryId: string) =>
  request<{
    memory_id: string
    useful: number
    not_useful: number
    total: number
  }>(`/feedback/summary/${memoryId}`)

// --- Spaced Repetition Review ---

export const getDueReviews = (opts?: { workspaceId?: string; limit?: number }) => {
  const params = new URLSearchParams()
  if (opts?.workspaceId) params.set('workspace_id', opts.workspaceId)
  if (opts?.limit) params.set('limit', String(opts.limit))
  const qs = params.toString()
  return request<ReviewItem[]>(`/review/due${qs ? `?${qs}` : ''}`)
}

export const submitReview = (memoryId: string, quality: number) =>
  request<ReviewResult>(`/review/${memoryId}`, {
    method: 'POST',
    body: JSON.stringify({ quality }),
  })

export const getReviewStats = (workspaceId?: string) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<ReviewStats>(`/review/stats${qs ? `?${qs}` : ''}`)
}

export const scheduleMemoryReview = (memoryId: string, workspaceId?: string) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<{ status: string; memory_id: string; next_review?: string }>(
    `/review/schedule/${memoryId}${qs ? `?${qs}` : ''}`,
    { method: 'POST' },
  )
}

export const undoReview = (memoryId: string, workspaceId?: string) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<{ status: string; memory_id: string; schedule: Record<string, unknown> }>(
    `/review/undo/${memoryId}${qs ? `?${qs}` : ''}`,
    { method: 'POST' },
  )
}
