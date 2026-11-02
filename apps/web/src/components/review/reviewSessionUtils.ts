export const DAILY_GOAL_MIN = 1
export const DAILY_GOAL_MAX = 200
export const DAILY_GOAL_DEFAULT = 20

/** 复习会话的可持久化状态：冻结的队列顺序 + 进度 + 筛选条件。 */
export interface PersistedReviewSession {
  queueIds: string[]
  currentIndex: number
  sessionReviewed: number
  sessionQualities: number[]
  filterMastery: string | null
  filterType: string | null
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** 从 localStorage 原文解析会话；损坏或格式不符时返回 null，按新会话处理。 */
export function parseReviewSession(raw: string | null): PersistedReviewSession | null {
  if (!raw) return null
  try {
    const data: unknown = JSON.parse(raw)
    if (typeof data !== 'object' || data === null) return null
    const record = data as Record<string, unknown>
    return {
      queueIds: Array.isArray(record.queueIds) ? record.queueIds.filter(isString) : [],
      currentIndex: isFiniteNumber(record.currentIndex)
        ? Math.max(0, Math.floor(record.currentIndex))
        : 0,
      sessionReviewed: isFiniteNumber(record.sessionReviewed)
        ? Math.max(0, Math.floor(record.sessionReviewed))
        : 0,
      sessionQualities: Array.isArray(record.sessionQualities)
        ? record.sessionQualities.filter(isFiniteNumber)
        : [],
      filterMastery: isString(record.filterMastery) ? record.filterMastery : null,
      filterType: isString(record.filterType) ? record.filterType : null,
    }
  } catch {
    return null
  }
}

/**
 * 按持久化的 ID 顺序从最新列表中重建队列。
 * 已删除的记忆自然缺席；队列为空时退回完整列表。
 */
export function rebuildQueue<T extends { memory_id: string }>(items: T[], queueIds: string[]): T[] {
  if (queueIds.length === 0) return items
  const byId = new Map(items.map((item) => [item.memory_id, item]))
  return queueIds.map((id) => byId.get(id)).filter((item): item is T => item !== undefined)
}

/** 恢复时夹取索引，允许等于 length（表示本轮已完成）。 */
export function normalizeIndex(index: number, length: number): number {
  if (!Number.isFinite(index) || index <= 0) return 0
  if (length <= 0) return 0
  return Math.min(Math.floor(index), length)
}

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
