import { callCommand } from './client'
import type { FontStatus } from '../types/fonts'

export function fetchFontStatus() {
  return callCommand<FontStatus>('get_font_status')
}

export function checkFonts(fonts: string[] = []) {
  return callCommand<FontStatus>('check_fonts', { fonts })
}

export function repairFonts(fonts: string[] = []) {
  return callCommand<FontStatus>('repair_fonts', { fonts })
}
