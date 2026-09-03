export interface SessionInfo {
  authenticated: boolean
  kind?: 'gui' | 'admin' | string
  csrf_token?: string
  expires_at?: number
}
