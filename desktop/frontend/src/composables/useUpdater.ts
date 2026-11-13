import { computed, ref } from 'vue'
import { getVersion } from '@tauri-apps/api/app'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { checkAppUpdate, installAppUpdate } from '../api/updater'
import { useToast } from './useToast'
import type { AppUpdateInfo, AppUpdateProgress } from '../types/updater'

const updateInfo = ref<AppUpdateInfo | null>(null)
const runtimeAppVersion = ref('0.3.1')
const checking = ref(false)
const installing = ref(false)
const dialogVisible = ref(false)
const checkError = ref('')
const progress = ref<AppUpdateProgress | null>(null)
let progressUnlisten: UnlistenFn | null = null
let startupChecked = false

getVersion()
  .then((ver) => {
    if (ver) runtimeAppVersion.value = ver
  })
  .catch(() => {})

export function useUpdater() {
  const toast = useToast()

  const currentVersion = computed(() => updateInfo.value?.current_version || runtimeAppVersion.value)
  const hasUpdate = computed(() => Boolean(updateInfo.value?.available && updateInfo.value?.version))
  const releaseUrl = computed(
    () => updateInfo.value?.release_url || 'https://github.com/javen-yan/stzy-paper-crawler/releases/latest',
  )

  async function ensureProgressListener() {
    if (progressUnlisten) return
    try {
      progressUnlisten = await listen<AppUpdateProgress>('updater:progress', (event) => {
        progress.value = event.payload
      })
    } catch {
      // Non-Tauri browser preview environment
    }
  }

  async function checkForUpdates(options: { silent?: boolean; openIfAvailable?: boolean } = {}) {
    if (checking.value || installing.value) return updateInfo.value
    checking.value = true
    checkError.value = ''
    try {
      const info = await checkAppUpdate()
      updateInfo.value = info
      if (info.available) {
        if (options.openIfAvailable || !options.silent) {
          dialogVisible.value = true
        }
      } else if (!options.silent) {
        toast.success(`当前已是最新版本 v${info.current_version}`)
      }
      return info
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error)
      checkError.value = msg
      if (!options.silent) {
        toast.error(error, '检查更新失败')
      }
      return null
    } finally {
      checking.value = false
    }
  }

  function runSilentStartupCheck() {
    if (startupChecked) return
    startupChecked = true
    window.setTimeout(() => {
      checkForUpdates({ silent: true, openIfAvailable: false }).catch(() => {})
    }, 3500)
  }

  function openUpdateDialog() {
    dialogVisible.value = true
  }

  async function startInstallUpdate() {
    if (installing.value) return
    await ensureProgressListener()
    installing.value = true
    progress.value = {
      phase: 'downloading',
      downloaded: 0,
      total: null,
      percent: 0,
    }
    try {
      await installAppUpdate()
    } catch (error) {
      installing.value = false
      progress.value = null
      toast.error(error, '在线更新失败，可点击下方按钮前往网页下载安装包')
    }
  }

  return {
    updateInfo,
    currentVersion,
    hasUpdate,
    releaseUrl,
    checking,
    installing,
    dialogVisible,
    checkError,
    progress,
    checkForUpdates,
    runSilentStartupCheck,
    openUpdateDialog,
    startInstallUpdate,
  }
}
