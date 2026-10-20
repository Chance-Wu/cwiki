import { API_BASE, authHeaders } from './base'

export const exportData = async (format: 'json' | 'zip'): Promise<Response> => {
  const res = await fetch(`${API_BASE}/data/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ format }),
  })
  if (!res.ok) throw new Error(`Export failed: ${res.status}`)
  return res
}

export const importData = async (
  file: File,
  strategy = 'skip',
): Promise<{ results?: { created: number } }> => {
  const formData = new FormData()
  formData.append('file', file)
  // FormData 不手动设 Content-Type（浏览器需自动生成 multipart boundary）
  const res = await fetch(`${API_BASE}/data/import?strategy=${strategy}`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })
  if (!res.ok) throw new Error(`Import failed: ${res.status}`)
  return res.json()
}

export const exportMarkdown = async (workspaceId?: string): Promise<Response> => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString()
  const res = await fetch(`${API_BASE}/export/markdown${qs ? `?${qs}` : ''}`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(`Markdown export failed: ${res.status}`)
  return res
}
