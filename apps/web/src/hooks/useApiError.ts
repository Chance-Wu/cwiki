import { useCallback } from 'react'
import { useTranslation } from '../i18n/I18nProvider'
import type { ApiErrorType } from '../lib/api/base'

interface UseApiErrorOptions {
  /** 错误发生时的额外回调（如日志上报） */
  onError?: (error: Error, errorType: ApiErrorType) => void
}

/**
 * 统一 API 错误处理 hook。
 *
 * 将 API 错误分类并返回用户友好的错误信息，支持：
 * - 网络错误（后端未启动/断网）
 * - 认证错误（401）
 * - 资源未找到（404）
 * - 服务器错误（5xx）
 * - 业务错误（其他）
 */
export function useApiError({ onError }: UseApiErrorOptions = {}) {
  const { t } = useTranslation()

  const handleError = useCallback(
    (error: unknown): string => {
      const err = error as Error & { status?: number; errorType?: ApiErrorType }
      const errorType = err.errorType ?? classifyError(err)

      // 额外回调（日志上报等）
      onError?.(err, errorType)

      // 开发环境打印详细错误
      if (import.meta.env.DEV) {
        console.error('[API Error]', {
          message: err.message,
          status: err.status,
          errorType,
        })
      }

      // 返回用户友好的错误信息
      return getErrorMessage(err, errorType, t)
    },
    [onError, t]
  )

  return { handleError }
}

/** 从错误对象推断错误类型 */
function classifyError(err: Error & { status?: number }): ApiErrorType {
  if (err.status === 0 || err.message.includes('fetch') || err.message.includes('网络')) {
    return 'network'
  }
  if (err.status === 401) return 'auth'
  if (err.status === 404) return 'not_found'
  if (err.status && err.status >= 500) return 'server'
  return 'unknown'
}

/** 获取用户友好的错误信息 */
function getErrorMessage(
  err: Error & { status?: number },
  errorType: ApiErrorType,
  t: { common: Record<string, string> }
): string {
  // 优先使用错误对象自带的 message（后端返回的业务错误）
  if (err.message && !err.message.includes('fetch') && !err.message.includes('网络')) {
    return err.message
  }

  // 根据错误类型返回通用提示
  switch (errorType) {
    case 'network':
      return t.common.networkError ?? '网络连接失败，请检查后端服务是否启动'
    case 'auth':
      return t.common.authError ?? '鉴权失败，请检查访问令牌'
    case 'not_found':
      return t.common.notFoundError ?? '请求的资源不存在'
    case 'server':
      return t.common.serverError ?? '服务器内部错误，请稍后重试'
    default:
      return t.common.unknownError ?? '未知错误，请重试'
  }
}
