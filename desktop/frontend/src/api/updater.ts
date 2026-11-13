import { callCommand } from './client'
import type { AppUpdateInfo } from '../types/updater'

export function checkAppUpdate() {
  return callCommand<AppUpdateInfo>('check_app_update')
}

export function installAppUpdate() {
  return callCommand<{ ok: boolean }>('install_app_update')
}
