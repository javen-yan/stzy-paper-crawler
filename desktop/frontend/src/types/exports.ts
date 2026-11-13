export interface ExportJob {
  id: string
  task_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | string
  display_name?: string
  file_path?: string
  size_bytes?: number
  included_count?: number
  error?: string
  created_at?: string
  expires_at?: string
}

export interface TaskExportView {
  current?: ExportJob | null
  historyUnavailable: boolean
}
