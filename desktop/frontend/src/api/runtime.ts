import { callCommand } from './client'
import type { RuntimeInfo } from '../types/runtime'

export function fetchRuntime() {
  return callCommand<RuntimeInfo>('get_runtime_info')
}
