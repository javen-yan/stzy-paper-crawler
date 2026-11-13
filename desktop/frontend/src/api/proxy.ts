import { callCommand } from './client'
import type { ProxyStatus } from '../types/proxy'

export function fetchProxyStatus() {
  return callCommand<ProxyStatus>('get_proxy_status')
}

export function bindLocalProxyIp() {
  return callCommand<{ ip: string; added: boolean; message: string }>('bind_local_proxy_ip')
}
