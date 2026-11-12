import { api, jsonBody } from './client'
import type { FontStatus } from '../types/fonts'

export function fetchFontStatus() {
  return api<FontStatus>('/api/v1/fonts/status')
}

export function checkFonts(fonts: string[] = []) {
  return api<FontStatus>('/api/v1/fonts/check', { method: 'POST', ...jsonBody({ fonts }) })
}

export function repairFonts(fonts: string[] = []) {
  return api<FontStatus>('/api/v1/fonts/repair', { method: 'POST', ...jsonBody({ fonts }) })
}
