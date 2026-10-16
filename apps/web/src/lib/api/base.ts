export const API_BASE = import.meta.env.VITE_API_BASE ?? '/v1'

/**
 * 统一请求入口：非 2xx 时优先取后端 FastAPI 返回的 detail 字段作为错误信息，
 * 解析不出 JSON 则退回状态行文本；调用方只需 catch Error.message 即可展示。
 */
export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const res = await fetch(`${API_BASE}${path}`, {
    headers,
    ...options,
  })
  if (!res.ok) {
    let message = `${res.status}: ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail)
        message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* 响应体解析失败时退回状态行文本 */
    }
    throw new Error(message)
  }
  return res.json()
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}
