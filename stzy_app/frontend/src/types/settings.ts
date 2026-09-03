export interface PublicSettings {
  output_dir?: string
  data_root?: string
  max_active_tasks?: number
  max_download_workers?: number
  max_convert_workers?: number
  max_export_workers?: number
  concurrency?: number
  max_retries?: number
  connect_timeout?: number
  read_timeout?: number
  list_delay_seconds?: number
  image_delay_seconds?: number
  list_max_retries?: number
  combo_failure_limit?: number
  file_type?: string
  max_pages_per_combo?: number | null
  export_ttl_hours?: number
  preview_max_pages?: number
  preview_max_pixels?: number
  preview_timeout_seconds?: number
  proxy_mode?: 'off' | 'fixed' | 'api' | string
  proxy_provider?: 'generic' | 'shenlong' | string
  proxy_pool?: string
  proxy_api_url?: string
  proxy_max_failures?: number
  proxy_cooldown_seconds?: number
  proxy_min_ttl_seconds?: number
  shenlong_whitelist_key?: string
  shenlong_whitelist_sign?: string
  study_phase_code?: string
  subject_code?: string
  subject_name?: string
  [key: string]: unknown
}
