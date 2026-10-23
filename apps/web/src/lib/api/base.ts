// 开发模式直连本机后端，不依赖 Vite 代理；构建/预览仍走相对路径
export const API_BASE =
  import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? 'http://127.0.0.1:5172/v1' : '/v1')

/**
 * Bearer token 的 localStorage 键：服务端启用 app.auth_token 后，在浏览器
 * 控制台执行 localStorage.setItem('cwiki_auth_token', '<token>') 即可。
 */
export const AUTH_TOKEN_STORAGE_KEY = 'cwiki_auth_token'

/** 服务端启用 auth_token 时返回 Authorization 头；未配置 token 则为空对象。 */
export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/**
 * 统一请求入口：非 2xx 时优先取后端 FastAPI 返回的 detail 字段作为错误信息，
 * 解析不出 JSON 则退回状态行文本；调用方只需 catch Error.message 即可展示。
 */
export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...authHeaders() }
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...headers, ...((options?.headers as Record<string, string>) ?? {}) },
  })
  if (!res.ok) {
    let message = `${res.status}: ${res.statusText}`
    if (res.status === 401) {
      message =
        '鉴权失败：服务端已启用 token，请在控制台执行 localStorage.setItem("cwiki_auth_token", "<token>") 后重试'
    } else {
      try {
        const body = await res.json()
        if (body?.detail)
          message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch {
        /* 响应体解析失败时退回状态行文本 */
      }
    }
    throw new Error(message)
  }
  // 204 No Content 或其他无响应体的情况
  if (res.status === 204 || res.headers.get('content-length') === '0') {
    return undefined as T
  }
  return res.json()
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}
