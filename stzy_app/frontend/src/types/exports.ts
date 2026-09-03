export interface ExportJob {
  id: string
  task_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | string
  display_name?: string
  error?: string
  created_at?: string
  expires_at?: string
}

export interface TaskExportView {
  current?: ExportJob | null
  historyUnavailable: boolean
}
