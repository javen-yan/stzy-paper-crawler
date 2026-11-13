<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import AppHeader from '../components/layout/AppHeader.vue'
import AppFooterLogPanel from '../components/layout/AppFooterLogPanel.vue'
import OfficeCoreDialog from '../components/layout/OfficeCoreDialog.vue'
import ProxyStatusPopover from '../components/layout/ProxyStatusPopover.vue'
import UpdateDialog from '../components/layout/UpdateDialog.vue'
import { useLayoutState } from '../composables/useLayoutState'
import { useTasks } from '../composables/useTasks'
import { useToast } from '../composables/useToast'
import { useUpdater } from '../composables/useUpdater'

interface TrayActionPayload {
  action: 'new_task' | 'navigate' | 'check_update' | 'tasks_changed' | string
  path?: string
  toast?: string
}

const route = useRoute()
const router = useRouter()
const toast = useToast()
const { requestNewTaskDialog } = useLayoutState()
const { refreshTasks } = useTasks()
const { runSilentStartupCheck, checkForUpdates } = useUpdater()
let trayUnlisten: UnlistenFn | null = null

const sectionTitle = computed(() => {
  const path = route.path
  if (path.startsWith('/tasks/')) return '任务详情'
  if (path.startsWith('/tasks')) return '任务管理'
  if (path.startsWith('/files')) return '本地文件'
  if (path.startsWith('/accounts')) return '账号管理'
  if (path.startsWith('/settings')) return '系统设置'
  return '试卷下载器'
})

const showFooterLog = computed(() => !route.path.startsWith('/tasks/'))

onMounted(async () => {
  runSilentStartupCheck()
  try {
    trayUnlisten = await listen<TrayActionPayload>('tray:action', async (event) => {
      const payload = event.payload || { action: '' }
      if (payload.action === 'new_task') {
        requestNewTaskDialog()
        if (route.path !== '/tasks') {
          await router.push('/tasks')
        }
      } else if (payload.action === 'navigate' && payload.path) {
        if (route.path !== payload.path) {
          await router.push(payload.path)
        }
      } else if (payload.action === 'check_update') {
        await checkForUpdates({ silent: false, openIfAvailable: true })
      } else if (payload.action === 'tasks_changed') {
        await refreshTasks({ archived: false, limit: 20, offset: 0 }).catch(() => {})
        if (payload.toast) {
          toast.success(payload.toast)
        }
      }
    })
  } catch {
    // Non-Tauri browser environment
  }
})

onBeforeUnmount(() => {
  if (trayUnlisten) {
    trayUnlisten()
    trayUnlisten = null
  }
})
</script>

<template>
  <div class="app-shell">
    <AppHeader />

    <div class="app-stage">
      <header class="stage-topbar">
        <div class="stage-breadcrumb">
          <span class="stage-section-dot" aria-hidden="true" />
          <strong class="stage-section-title">{{ sectionTitle }}</strong>
        </div>

        <div class="stage-toolbar">
          <ProxyStatusPopover />
        </div>
      </header>

      <main class="workspace" tabindex="-1">
        <div class="workspace-inner">
          <RouterView />
        </div>
      </main>

      <AppFooterLogPanel v-if="showFooterLog" />
    </div>

    <OfficeCoreDialog />
    <UpdateDialog />
  </div>
</template>
