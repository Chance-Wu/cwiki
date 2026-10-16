import { request } from './base'
import type { TaskQueueStatusResponse, TaskQueueRetryResponse } from './types'

// --- 任务队列诊断 ---

export const getTaskQueueStatus = () => request<TaskQueueStatusResponse>('/task-queue-status')

/** 手动重试 FAILED 任务：重置为 PENDING 并重新入队；任务不存在或状态非 FAILED 时后端返回 404 */
export const retryTaskQueueTask = (taskId: string) =>
  request<TaskQueueRetryResponse>('/task-queue/retry', {
    method: 'POST',
    body: JSON.stringify({ task_id: taskId }),
  })
