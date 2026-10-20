import { request, type PaginatedResponse } from './base'
import type { Workspace } from './types'

let _defaultWorkspaceId: string | undefined

export async function getDefaultWorkspaceId(): Promise<string | undefined> {
  if (_defaultWorkspaceId) return _defaultWorkspaceId
  // 默认工作区由后端解析为 active 记忆最多者；/workspaces 列表按创建时间
  // 倒序，取第一项会命中最新创建的空工作区（复习页全零的根因）
  try {
    const ws = await request<Workspace>(`/workspaces/default`)
    _defaultWorkspaceId = ws.id
    return _defaultWorkspaceId
  } catch {
    return undefined
  }
}

export async function getWorkspaces(): Promise<Workspace[]> {
  const res = await request<PaginatedResponse<Workspace>>(`/workspaces?limit=100`)
  return res.items
}
