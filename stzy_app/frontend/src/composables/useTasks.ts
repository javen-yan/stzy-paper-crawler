import { computed, ref } from 'vue'
import { createTask, estimateTaskPreview, fetchTask as fetchTaskApi, fetchTaskLogs, fetchTaskResources, listTasks, taskAction } from '../api/tasks'
import type { LogLine, Task, TaskCreateForm, TaskCreateRequest, TaskResource } from '../types/tasks'
import { createClientId } from '../utils/id'

export const statusText: Record<string, string> = {
  queued: '等待',
  running: '下载中',
  pausing: '暂停中',
  paused: '已暂停',
  completed: '已完成',
  partial_completed: '部分完成',
  failed: '失败',
  auth_expired: '登录失效',
  cancelled: '已取消',
  interrupted: '已中断',
}

export function taskStatusLabel(task: Task | null | undefined) {
  if (!task) return '等待选择'
  if (task.status === 'running' && task.mode === 'estimate') return '预估中'
  if (task.status === 'completed' && task.mode === 'estimate') return '可下载'
  return statusText[task.status] || task.status
}

const tasks = ref<Task[]>([])
const selectedTaskId = ref('')
const logs = ref<LogLine[]>([])
const resources = ref<TaskResource[]>([])
const logCursor = ref(0)
const LOG_FETCH_LIMIT = 80
const LOG_TAIL_LIMIT = 200
const LOG_BUFFER_LIMIT = 200
let logRefreshing = false

export function useTasks() {
  const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value) || null)

  async function refreshTasks(params: { archived?: boolean; limit?: number; offset?: number } = {}) {
    const payload = await listTasks(params)
    tasks.value = payload.items
    if (!selectedTaskId.value && tasks.value.length) selectedTaskId.value = tasks.value[0].id
    return payload
  }

  async function refreshSelectedTask() {
    if (!selectedTaskId.value) return null
    const task = await fetchTaskApi(selectedTaskId.value)
    const existingIndex = tasks.value.findIndex((item) => item.id === task.id)
    if (existingIndex >= 0) tasks.value[existingIndex] = task
    else tasks.value.unshift(task)
    return task
  }

  async function selectTask(taskId: string, options: { includeLogs?: boolean; includeResources?: boolean } = {}) {
    const includeLogs = options.includeLogs ?? true
    const includeResources = options.includeResources ?? true
    const taskChanged = selectedTaskId.value !== taskId
    selectedTaskId.value = taskId
    const existingIndex = tasks.value.findIndex((task) => task.id === taskId)
    const task = await fetchTaskApi(taskId)
    if (existingIndex >= 0) tasks.value[existingIndex] = task
    else tasks.value.unshift(task)
    if (taskChanged || includeLogs) {
      logs.value = []
      logCursor.value = 0
    }
    const jobs: Array<Promise<unknown> | undefined> = []
    if (includeLogs) {
      jobs.push(refreshLogs(true))
    }
    if (includeResources) jobs.push(refreshResources())
    await Promise.all(jobs)
  }

  async function refreshLogs(reset = false) {
    if (!selectedTaskId.value) return
    if (logRefreshing) return
    logRefreshing = true
    if (reset) {
      logs.value = []
      logCursor.value = 0
    }
    try {
      const shouldTail = reset || (!logs.value.length && logCursor.value <= 0)
      const payload = await fetchTaskLogs(
        selectedTaskId.value,
        shouldTail ? 0 : logCursor.value,
        shouldTail ? LOG_TAIL_LIMIT : LOG_FETCH_LIMIT,
        shouldTail,
      )
      const knownIds = new Set(logs.value.map((line) => line.id))
      logs.value.push(...payload.items.filter((line) => !knownIds.has(line.id)))
      if (logs.value.length > LOG_BUFFER_LIMIT) {
        logs.value = logs.value.slice(-LOG_BUFFER_LIMIT)
      }
      logCursor.value = payload.next_cursor
    } finally {
      logRefreshing = false
    }
  }

  async function refreshResources(params: { limit?: number; offset?: number; status?: string } = {}) {
    if (!selectedTaskId.value) return
    const payload = await fetchTaskResources(selectedTaskId.value, params.limit, params.offset, params.status)
    resources.value = payload.items
    return payload
  }

  async function submitTask(form: TaskCreateForm) {
    const payload = taskFormToRequest(form)
    const task = await createTask(payload)
    await refreshTasks()
    await selectTask(task.id)
    return task
  }

  async function estimateTask(form: TaskCreateForm) {
    const payload = { ...taskFormToRequest(form), mode: 'estimate' }
    return estimateTaskPreview(payload)
  }

  async function createDownloadFromEstimate(task: Task) {
    const spec = task.spec || {}
    const created = await createTask({
      mode: 'crawl',
      title: `${task.title || '预估结果'} - 下载`,
      filters: (spec.filters || {}) as Record<string, unknown>,
      filter_labels: (spec.filter_labels || {}) as Record<string, unknown>,
      subjects: (spec.subjects || []) as Array<Record<string, string>>,
      settings: (spec.settings || {}) as Record<string, unknown>,
      idempotency_key: createClientId('task'),
    })
    await refreshTasks()
    await selectTask(created.id)
    return created
  }

  async function runTaskAction(taskId: string, action: 'pause' | 'resume' | 'cancel' | 'archive') {
    await taskAction(taskId, action)
    await refreshTasks()
    if (selectedTaskId.value === taskId) await refreshResources()
  }

  return {
    tasks,
    selectedTaskId,
    selectedTask,
    logs,
    resources,
    statusText,
    refreshTasks,
    refreshSelectedTask,
    selectTask,
    refreshLogs,
    refreshResources,
    estimateTask,
    submitTask,
    createDownloadFromEstimate,
    runTaskAction,
  }
}

function taskFormToRequest(form: TaskCreateForm): TaskCreateRequest {
  const filters: Record<string, unknown> = {
  }
  if (form.scenes.length) filters.scenes = form.scenes
  if (form.grades.length) filters.grades = form.grades
  if (form.terms.length) filters.terms = form.terms
  if (form.provinces.length) filters.provinces = form.provinces
  if (form.years.length) filters.years = form.years
  if (form.ranks.length) filters.ranks = form.ranks
  return {
    mode: form.mode,
    title: form.title,
    filters,
    filter_labels: form.filterLabels || {},
    subjects: form.subjects.map((code) => ({ code, name: form.subjectLabels?.[code] || '' })),
    settings: { study_phase_code: form.studyPhase, file_type: form.fileType, max_pages_per_combo: form.maxPagesPerCombo },
    idempotency_key: createClientId('task'),
  }
}
