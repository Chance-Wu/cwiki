import { useState, useCallback, useRef, useEffect } from 'react'

interface UseRetryOptions {
  /** 最大重试次数，默认 3 */
  maxRetries?: number
  /** 重试间隔（毫秒），默认 1000 */
  retryDelay?: number
  /** 是否启用指数退避，默认 true */
  exponentialBackoff?: boolean
  /** 判断是否应该重试的函数 */
  shouldRetry?: (error: unknown, attempt: number) => boolean
}

interface UseRetryReturn {
  /** 当前重试次数 */
  retryCount: number
  /** 是否正在重试 */
  isRetrying: boolean
  /** 执行带重试的操作 */
  execute: <T>(fn: () => Promise<T>) => Promise<T>
  /** 手动重置重试状态 */
  reset: () => void
}

/**
 * 自动重试 hook。
 *
 * 用于处理临时性错误（如网络波动），支持：
 * - 可配置的最大重试次数
 * - 固定间隔或指数退避
 * - 自定义重试条件判断
 */
export function useRetry(options: UseRetryOptions = {}): UseRetryReturn {
  const {
    maxRetries = 3,
    retryDelay = 1000,
    exponentialBackoff = true,
    shouldRetry,
  } = options

  const [retryCount, setRetryCount] = useState(0)
  const [isRetrying, setIsRetrying] = useState(false)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  const reset = useCallback(() => {
    setRetryCount(0)
    setIsRetrying(false)
  }, [])

  const execute = useCallback(
    async <T>(fn: () => Promise<T>): Promise<T> => {
      let lastError: unknown
      let attempts = 0

      const tryOnce = async (): Promise<T | null> => {
        try {
          const result = await fn()
          if (mountedRef.current) {
            setRetryCount(0)
            setIsRetrying(false)
          }
          return result
        } catch (error) {
          lastError = error
          attempts++

          // 检查是否应该重试
          const canRetry = attempts <= maxRetries
          const shouldRetryError = shouldRetry
            ? shouldRetry(error, attempts)
            : isRetryableError(error)

          if (!canRetry || !shouldRetryError) {
            if (mountedRef.current) {
              setIsRetrying(false)
            }
            throw error
          }

          // 计算延迟时间
          const delay = exponentialBackoff
            ? retryDelay * Math.pow(2, attempts - 1)
            : retryDelay

          if (mountedRef.current) {
            setRetryCount(attempts)
            setIsRetrying(true)
          }

          // 等待后重试
          await new Promise((resolve) => setTimeout(resolve, delay))
          return null
        }
      }

      // 循环重试直到成功或达到最大次数
      while (attempts <= maxRetries) {
        const result = await tryOnce()
        if (result !== null) {
          return result
        }
      }

      throw lastError
    },
    [maxRetries, retryDelay, exponentialBackoff, shouldRetry]
  )

  return {
    retryCount,
    isRetrying,
    execute,
    reset,
  }
}

/** 判断错误是否可重试（网络错误、超时等） */
function isRetryableError(error: unknown): boolean {
  if (!(error instanceof Error)) return false

  const message = error.message.toLowerCase()

  // 网络错误
  if (
    message.includes('fetch') ||
    message.includes('network') ||
    message.includes('网络') ||
    message.includes('timeout')
  ) {
    return true
  }

  // HTTP 状态码判断
  const err = error as Error & { status?: number }
  if (err.status) {
    // 5xx 服务器错误可重试
    if (err.status >= 500) return true
    // 429 请求过多可重试
    if (err.status === 429) return true
    // 408 请求超时可重试
    if (err.status === 408) return true
  }

  return false
}
