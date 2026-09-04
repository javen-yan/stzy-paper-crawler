import { api, jsonBody } from './client'
import type { LogLine, Task, TaskCreateRequest, TaskEstimateResult, TaskResource } from '../types/tasks'

export function listTasks(params: { archived?: boolean; limit?: number; offset?: number } = {}) {
  const query = new URLSearchParams()
  if (params.archived) query.set('archived', 'true')
  if (params.limit) query.set('limit', String(params.limit))
  if (params.offset) query.set('offset', String(params.offset))
  return api<{ items: Task[] }>(`/api/v1/tasks${query.size ? `?${query}` : ''}`)
}

export function createTask(payload: TaskCreateRequest) {
  return api<Task>('/api/v1/tasks', { method: 'POST', ...jsonBody(payload) })
}

export function estimateTaskPreview(payload: TaskCreateRequest) {
  return api<TaskEstimateResult>('/api/v1/tasks/estimate', { method: 'POST', ...jsonBody(payload) })
}

export function fetchTask(taskId: string) {
  return api<Task>(`/api/v1/tasks/${encodeURIComponent(taskId)}`)
}

export function taskAction(taskId: string, action: 'pause' | 'resume' | 'cancel' | 'archive') {
  return api<Task>(`/api/v1/tasks/${encodeURIComponent(taskId)}/${action}`, { method: 'POST' })
}

export function fetchTaskLogs(taskId: string, after = 0, limit = 300, tail = false) {
  const query = new URLSearchParams({ after: String(after), limit: String(limit) })
  if (tail) query.set('tail', 'true')
  return api<{ items: LogLine[]; next_cursor: number }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/logs?${query}`,
  )
}

export function fetchTaskResources(taskId: string, limit = 100, offset = 0, status = '') {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) query.set('status', status)
  return api<{ items: TaskResource[]; total: number; status_counts: Record<string, number> }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/resources?${query}`,
  )
}
