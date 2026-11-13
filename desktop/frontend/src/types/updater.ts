export interface AppUpdateInfo {
  current_version: string
  available: boolean
  version?: string
  date?: string
  body?: string
  release_url: string
  running_tasks?: number
}

export interface AppUpdateProgress {
  phase: 'downloading' | 'pausing_tasks' | 'installing' | 'restarting' | string
  downloaded: number
  total: number | null
  percent: number
}
