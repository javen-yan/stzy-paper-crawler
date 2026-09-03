export interface Account {
  name: string
  enabled: boolean
  health_label: string
  account_type_label: string
  usable: boolean
  in_cooldown?: boolean
  import_method?: string
  login_phone?: string
  fail_count?: number
  last_error?: string
  cooldown_until?: string
  last_checked_at?: string
  surplus_num?: number | null
  rank?: number | null
  user_type?: number | null
  last_verified_at?: string
  error?: string
}

export interface AccountPayload {
  name: string
  cookie: string
  access_token: string
  user_agent: string
  request_headers_json: string
  login_phone: string
  login_password: string
  enabled: boolean
}

export interface AccountImportPayload {
  raw: string
  name?: string
}

export interface PhoneLoginPayload {
  phone: string
  password?: string
  name?: string
}
