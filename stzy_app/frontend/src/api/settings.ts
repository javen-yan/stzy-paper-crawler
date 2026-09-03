import { api, jsonBody } from './client'
import type { PublicSettings } from '../types/settings'

export function fetchSettings() {
  return api<PublicSettings>('/api/v1/settings')
}

export function updateSettings(payload: Partial<PublicSettings>) {
  return api<PublicSettings>('/api/v1/settings', { method: 'PUT', ...jsonBody(payload) })
}
