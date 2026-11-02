import { useEffect, useRef } from 'react'
import { useReviewStats } from './useReview'
import { useTranslation } from '../i18n/I18nProvider'

export const REVIEW_REMINDER_KEY = 'cwiki-review-reminder'
const LAST_NOTIFIED_KEY = 'cwiki-review-reminder-date'

export function isReviewReminderEnabled(): boolean {
  try {
    return localStorage.getItem(REVIEW_REMINDER_KEY) === '1'
  } catch {
    return false
  }
}

export function setReviewReminderEnabled(enabled: boolean): void {
  try {
    if (enabled) localStorage.setItem(REVIEW_REMINDER_KEY, '1')
    else localStorage.removeItem(REVIEW_REMINDER_KEY)
  } catch {
    /* 忽略存储不可用 */
  }
}

function todayKey(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

/**
 * 到期时每天最多推送一次浏览器通知。
 * 没有 Service Worker / Push：只有 cwiki 页面打开期间才可靠，
 * 标题徽标与首页到期卡片是主路径，通知只是增强。
 */
export function useReviewReminder(): void {
  const { data: stats } = useReviewStats()
  const { t } = useTranslation()
  const notifiedRef = useRef(false)

  useEffect(() => {
    if (notifiedRef.current) return
    if (!stats || stats.due_now <= 0) return
    if (!isReviewReminderEnabled()) return
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return

    const today = todayKey()
    try {
      if (localStorage.getItem(LAST_NOTIFIED_KEY) === today) return
      localStorage.setItem(LAST_NOTIFIED_KEY, today)
    } catch {
      /* 存储不可用时仅靠内存去重 */
    }

    notifiedRef.current = true
    const notification = new Notification(t.review.reminderTitle, {
      body: t.review.reminderBody.replace('{n}', String(stats.due_now)),
      tag: 'cwiki-review-reminder',
    })
    notification.onclick = () => {
      window.focus()
      window.location.href = '/review'
      notification.close()
    }
  }, [stats, t])
}
