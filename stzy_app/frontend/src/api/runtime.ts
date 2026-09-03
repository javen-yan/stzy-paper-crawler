import { api } from './client'
import type { RuntimeInfo } from '../types/runtime'

export function fetchRuntime() {
  return api<RuntimeInfo>('/api/v1/runtime')
}
