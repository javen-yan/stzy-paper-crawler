import { callCommand } from './client'
import type { PublicSettings } from '../types/settings'

export function fetchSettings() {
  return callCommand<PublicSettings>('get_settings')
}

export function updateSettings(payload: Partial<PublicSettings>) {
  return callCommand<PublicSettings>('update_settings', { payload })
}
