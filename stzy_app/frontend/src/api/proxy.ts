import { api } from './client'
import type { ProxyStatus } from '../types/proxy'

export function fetchProxyStatus() {
  return api<ProxyStatus>('/api/v1/proxy/status')
}

export function bindLocalProxyIp() {
  return api<{ ip: string; added: boolean; message: string }>('/api/v1/proxy/bind-local-ip', { method: 'POST' })
}
