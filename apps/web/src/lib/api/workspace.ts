import { request, type PaginatedResponse } from './base'
import type { Workspace } from './types'

let _defaultWorkspaceId: string | undefined

export async function getDefaultWorkspaceId(): Promise<string | undefined> {
  if (_defaultWorkspaceId) return _defaultWorkspaceId
  const res = await request<PaginatedResponse<Workspace>>(`/workspaces?limit=100`)
  if (res.items.length > 0) {
    _defaultWorkspaceId = res.items[0].id
    return _defaultWorkspaceId
  }
  return undefined
}

export async function getWorkspaces(): Promise<Workspace[]> {
  const res = await request<PaginatedResponse<Workspace>>(`/workspaces?limit=100`)
  return res.items
}
