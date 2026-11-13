<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import { RefreshCw, Terminal } from 'lucide-vue-next'
import AppHeader from '../components/layout/AppHeader.vue'
import AppFooterLogPanel from '../components/layout/AppFooterLogPanel.vue'
import ProxyStatusPopover from '../components/layout/ProxyStatusPopover.vue'
import { useLayoutState } from '../composables/useLayoutState'

const route = useRoute()
const { footerExpanded, toggleFooter } = useLayoutState()

const sectionMeta = computed(() => {
  const path = route.path
  if (path.startsWith('/tasks/')) {
    return { title: '任务详情', subtitle: '查看实时采集进度、资源明细与本地成果' }
  }
  if (path.startsWith('/tasks')) {
    return { title: '任务中心', subtitle: '试卷智能筛选、批量采集与原生 PDF 转换' }
  }
  if (path.startsWith('/files')) {
    return { title: '文件库', subtitle: '按学科/年级目录浏览本地试卷并导出压缩包' }
  }
  if (path.startsWith('/accounts')) {
    return { title: '账号池', subtitle: '多账号加密托管、VIP 优先调度与状态巡检' }
  }
  if (path.startsWith('/settings')) {
    return { title: '系统设置', subtitle: '下载目录、代理池、并发速率与排版字体配置' }
  }
  return { title: '工作台', subtitle: 'STZY Native Desktop Studio' }
})
</script>

<template>
  <div class="app-shell">
    <AppHeader />

    <div class="app-stage">
      <header class="stage-topbar">
        <div class="stage-breadcrumb">
          <span class="stage-section-dot" aria-hidden="true" />
          <strong class="stage-section-title">{{ sectionMeta.title }}</strong>
          <span class="stage-section-divider" aria-hidden="true">/</span>
          <span class="stage-section-subtitle">{{ sectionMeta.subtitle }}</span>
        </div>

        <div class="stage-toolbar">
          <ProxyStatusPopover />
          <span class="header-tool-divider" aria-hidden="true" />
          <el-tooltip :content="footerExpanded ? '收起实时日志台' : '展开实时日志台'" placement="bottom">
            <el-button
              class="icon-tool-button"
              :class="{ 'is-active': footerExpanded }"
              circle
              aria-label="切换实时日志台"
              @click="toggleFooter"
            >
              <Terminal :size="15" />
            </el-button>
          </el-tooltip>
          <el-tooltip content="刷新当前视图" placement="bottom">
            <el-button
              class="icon-tool-button"
              :icon="RefreshCw"
              circle
              aria-label="刷新当前视图"
              @click="$router.go(0)"
            />
          </el-tooltip>
        </div>
      </header>

      <main class="workspace" tabindex="-1">
        <div class="workspace-inner">
          <RouterView />
        </div>
      </main>

      <AppFooterLogPanel />
    </div>
  </div>
</template>
