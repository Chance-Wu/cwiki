import { request } from './base'
import type { PaginatedResponse } from './base'
import type { AgentSession, AgentProfile, AgentStats, SessionNote } from './types'

// --- Agent Sessions ---

export const getAgentSessions = (
  workspaceId?: string | null,
  opts?: {
    limit?: number
    offset?: number
    agent?: string
    outcome?: string
    since?: string
    until?: string
  },
) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  if (opts?.limit) params.set('limit', String(opts.limit))
  if (opts?.offset) params.set('offset', String(opts.offset))
  if (opts?.agent) params.set('agent', opts.agent)
  if (opts?.outcome) params.set('outcome', opts.outcome)
  if (opts?.since) params.set('since', opts.since)
  if (opts?.until) params.set('until', opts.until)
  const qs = params.toString()
  return request<PaginatedResponse<AgentSession>>(`/agent-sessions${qs ? `?${qs}` : ''}`)
}

// --- Agents ---

export const getAgentProfile = (workspaceId: string, agentId: string) =>
  request<AgentProfile>(`/agents/profiles/${workspaceId}/${agentId}`)

export const getAgentStats = (workspaceId?: string | null) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  return request<AgentStats>(`/agent-sessions/stats${qs ? `?${qs}` : ''}`)
}

// --- Session Notes ---

export const getSessionNotes = (opts?: {
  sessionId?: string
  workspaceId?: string
  formalized?: boolean
  signalType?: string
  limit?: number
  offset?: number
}) => {
  const params = new URLSearchParams()
  if (opts?.sessionId) params.set('session_id', opts.sessionId)
  if (opts?.workspaceId) params.set('workspace_id', opts.workspaceId)
  if (opts?.formalized !== undefined) params.set('formalized', String(opts.formalized))
  if (opts?.signalType) params.set('signal_type', opts.signalType)
  if (opts?.limit) params.set('limit', String(opts.limit))
  if (opts?.offset) params.set('offset', String(opts.offset))
  const qs = params.toString()
  return request<PaginatedResponse<SessionNote>>(`/session-notes${qs ? `?${qs}` : ''}`)
}

export const searchSessionNotes = (opts: {
  workspaceId: string
  q: string
  days?: number
  limit?: number
  signalType?: string
}) => {
  const params = new URLSearchParams({ workspace_id: opts.workspaceId, q: opts.q })
  if (opts.days) params.set('days', String(opts.days))
  if (opts.limit) params.set('limit', String(opts.limit))
  if (opts.signalType) params.set('signal_type', opts.signalType)
  return request<PaginatedResponse<SessionNote>>(`/session-notes/search?${params.toString()}`)
}

export const formalizeNote = (noteId: string, body?: { memory_id?: string }) =>
  request<SessionNote>(`/session-notes/${noteId}/formalize`, {
    method: 'PATCH',
    body: JSON.stringify(body ?? {}),
  })
