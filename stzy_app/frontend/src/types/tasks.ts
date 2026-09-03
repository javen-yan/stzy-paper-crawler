export type TaskStatus =
  | 'queued'
  | 'running'
  | 'pausing'
  | 'paused'
  | 'completed'
  | 'partial_completed'
  | 'failed'
  | 'auth_expired'
  | 'cancelled'
  | 'interrupted'
  | string

export interface Task {
  id: string
  mode: 'crawl' | 'estimate' | string
  status: TaskStatus
  archived?: boolean
  title: string
  task_title?: string
  task_display_name?: string
  error: string
  stats: Record<string, unknown>
  spec?: {
    title?: string
    mode?: string
    filters?: Record<string, unknown>
    filter_labels?: Record<string, unknown>
    subjects?: Array<Record<string, string>>
    settings?: Record<string, unknown>
    [key: string]: unknown
  }
  output_dir?: string
  active_proxy?: string
  created_at: string
  started_at?: string
  ended_at?: string
  updated_at: string
}

export interface TaskCreateForm {
  title: string
  mode: 'crawl' | 'estimate'
  studyPhase: string
  fileType: string
  downloadPaid: boolean
  maxPagesPerCombo?: number
  subjectLabels?: Record<string, string>
  filterLabels?: Record<string, string[]>
  subjects: string[]
  scenes: string[]
  grades: string[]
  terms: string[]
  provinces: string[]
  years: string[]
  ranks: string[]
}

export interface TaskCreateRequest {
  mode: string
  title: string
  filters: Record<string, unknown>
  filter_labels?: Record<string, unknown>
  subjects: Array<Record<string, string>>
  settings?: Record<string, unknown>
  idempotency_key: string
}

export interface TaskEstimateResult {
  stats: Record<string, unknown>
  logs: LogLine[]
  spec: {
    title?: string
    mode?: string
    filters?: Record<string, unknown>
    filter_labels?: Record<string, unknown>
    subjects?: Array<Record<string, string>>
    settings?: Record<string, unknown>
    [key: string]: unknown
  }
}

export interface LogLine {
  id: number
  level: string
  message: string
  created_at: string
}

export interface TaskResource {
  id?: string
  resource_id?: string
  resource_name?: string
  name?: string
  title?: string
  subject?: string
  year?: string
  scene?: string
  rank?: string
  province?: string
  grade?: string
  term?: string
  price?: number
  page_count?: number
  image_count?: number
  local_dir?: string
  status?: string
  error?: string
  [key: string]: unknown
}

export type TaskDetailTabKey = 'overview' | 'logs' | 'config' | 'resources' | 'files' | 'exports' | 'issues'

export interface TaskOverviewStats {
  total: number
  completed: number
  failed: number
  skipped: number
}

export interface TaskConfigSnapshot {
  filters: Record<string, unknown>
  subjects: Array<Record<string, string>>
  settings: Record<string, unknown>
}

export interface TaskIssue {
  type: 'account' | 'proxy' | 'resource' | 'file' | 'task'
  title: string
  detail: string
  recovery: string
}
