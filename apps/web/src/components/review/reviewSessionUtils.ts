export const DAILY_GOAL_MIN = 1
export const DAILY_GOAL_MAX = 200
export const DAILY_GOAL_DEFAULT = 20

export function clampGoal(value: number): number {
  if (Number.isNaN(value)) return DAILY_GOAL_DEFAULT
  return Math.min(DAILY_GOAL_MAX, Math.max(DAILY_GOAL_MIN, Math.round(value)))
}

// 秒 → mm:ss，超过一小时用 h:mm:ss
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(sec).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}
