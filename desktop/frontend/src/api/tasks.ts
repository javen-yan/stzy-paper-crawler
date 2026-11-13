import { callCommand } from './client'
import type { LogLine, Task, TaskCreateRequest, TaskEstimateResult, TaskResource } from '../types/tasks'

export function listTasks(params: { archived?: boolean; limit?: number; offset?: number } = {}) {
  return callCommand<{ items: Task[] }>('list_tasks', {
    archived: params.archived ?? false,
    limit: params.limit,
    offset: params.offset,
  })
}

export function createTask(payload: TaskCreateRequest) {
  return callCommand<Task>('create_task', { payload })
}

export function estimateTaskPreview(payload: TaskCreateRequest) {
  return callCommand<TaskEstimateResult>('estimate_task_preview', { payload })
}

export function fetchTask(taskId: string) {
  return callCommand<Task>('get_task', { task_id: taskId })
}

export function taskAction(taskId: string, action: 'pause' | 'resume' | 'cancel' | 'archive') {
  return callCommand<Task>('task_action', { task_id: taskId, action })
}

export function fetchTaskLogs(taskId: string, after = 0, limit = 300, tail = false) {
  return callCommand<{ items: LogLine[]; next_cursor: number }>('get_task_logs', {
    task_id: taskId,
    after,
    limit,
    tail,
  })
}

export function fetchTaskResources(taskId: string, limit = 100, offset = 0, status = '') {
  return callCommand<{ items: TaskResource[]; total: number; status_counts: Record<string, number> }>(
    'get_task_resources',
    {
      task_id: taskId,
      limit,
      offset,
      status: status || undefined,
    },
  )
}
