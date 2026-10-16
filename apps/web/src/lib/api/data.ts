import { API_BASE } from './base'

export const exportData = async (format: 'json' | 'zip'): Promise<Response> => {
  const res = await fetch(`${API_BASE}/data/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  const res = await fetch(`${API_BASE}/data/import?strategy=${strategy}`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) throw new Error(`Import failed: ${res.status}`)
  return res.json()
}
