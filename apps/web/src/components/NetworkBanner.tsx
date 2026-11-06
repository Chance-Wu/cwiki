import { motion, AnimatePresence } from 'framer-motion'
import { WifiOff, RefreshCw } from 'lucide-react'
import { useNetworkStatus } from '../hooks/useNetworkStatus'
import { useTranslation } from '../i18n/I18nProvider'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

/**
 * 全局网络状态横幅：当检测到离线或 API 不可用时显示顶部提示。
 *
 * 复用 useNetworkStatus（基于 health 端点 + online/offline 事件），
 * 不额外发起轮询。
 */
export default function NetworkBanner() {
  const isOnline = useNetworkStatus()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [retrying, setRetrying] = useState(false)

  const handleRetry = async () => {
    setRetrying(true)
    try {
      await queryClient.invalidateQueries({ queryKey: ['health'] })
    } finally {
      setTimeout(() => setRetrying(false), 500)
    }
  }

  if (isOnline) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ y: -40, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: -40, opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed top-0 left-0 right-0 z-50 flex items-center justify-center gap-3 px-4 py-2 bg-warning-bg border-b border-warning-border text-warning-fg text-xs font-medium shadow-warm-sm"
        role="alert"
        aria-live="polite"
      >
        <WifiOff size={14} aria-hidden="true" />
        <span>{t.common.networkError ?? '网络连接失败，请检查后端服务是否启动'}</span>
        <button
          onClick={handleRetry}
          disabled={retrying}
          className="ml-2 flex items-center gap-1 px-2 py-0.5 rounded bg-warning/20 hover:bg-warning/30 disabled:opacity-50 transition-colors"
          aria-label={t.common.retry}
        >
          <RefreshCw size={12} className={retrying ? 'animate-spin' : ''} />
          <span>{t.common.retry}</span>
        </button>
      </motion.div>
    </AnimatePresence>
  )
}
