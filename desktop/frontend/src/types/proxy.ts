export interface ProxyStatusItem {
  id: string
  source: string
  address: string
  status: string
  running_count: number
  lease_task_id?: string
  lease_resource_name?: string
  cooldown_until?: number
  failure_count?: number
}

export interface RunningTask {
  id: string
  title: string
  mode: string
  active_proxy: string
}

export interface ProxyStatus {
  my_ip: string
  my_ip_status?: {
    ok: boolean
    ip: string
    source: string
    error: string
  }
  proxy_mode: 'off' | 'fixed' | 'api' | string
  proxy_provider: 'generic' | 'shenlong' | string
  proxy_api_configured: boolean
  pool_size: number
  target_proxy_count: number
  available_proxy_count: number
  leased_proxy_count: number
  cooldown_proxy_count: number
  running_task_count: number
  running_proxy_count: number
  running_tasks: RunningTask[]
  effective_download_workers: number
  items: ProxyStatusItem[]
}
