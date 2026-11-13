<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppHeader from '../components/layout/AppHeader.vue'
import AppFooterLogPanel from '../components/layout/AppFooterLogPanel.vue'
import OfficeCoreDialog from '../components/layout/OfficeCoreDialog.vue'
import ProxyStatusPopover from '../components/layout/ProxyStatusPopover.vue'
import UpdateDialog from '../components/layout/UpdateDialog.vue'
import { useUpdater } from '../composables/useUpdater'

const route = useRoute()
const { runSilentStartupCheck } = useUpdater()

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

onMounted(() => {
  runSilentStartupCheck()
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
