import { api, jsonBody, setCsrfToken } from './client'
import type { SessionInfo } from '../types/auth'

export async function fetchSession() {
  const session = await api<SessionInfo>('/api/v1/auth/session')
  setCsrfToken(session.csrf_token || '')
  return session
}

export async function login(password: string) {
  const session = await api<SessionInfo>('/api/v1/auth/login', {
    method: 'POST',
    ...jsonBody({ password }),
  })
  setCsrfToken(session.csrf_token || '')
  return session
}

export async function bootstrap(token: string) {
  const session = await api<SessionInfo>('/api/v1/auth/bootstrap', {
    method: 'POST',
    ...jsonBody({ token }),
  })
  setCsrfToken(session.csrf_token || '')
  return session
}

export async function logout() {
  await api<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST' })
  setCsrfToken('')
}
