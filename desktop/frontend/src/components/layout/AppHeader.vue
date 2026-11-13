<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  FolderOpen,
  Layers,
  LayoutDashboard,
  Settings,
  ShieldCheck,
  Terminal,
  Users,
} from 'lucide-vue-next'
import { useLayoutState } from '../../composables/useLayoutState'
import { useRuntime } from '../../composables/useRuntime'
import { useTasks } from '../../composables/useTasks'

const route = useRoute()
const router = useRouter()
const { runtime } = useRuntime()
const { tasks } = useTasks()
const { footerExpanded, toggleFooter } = useLayoutState()

const runningCount = computed(() => tasks.value.filter((task) => task.status === 'running').length)

const primaryNavItems = computed(() => [
  { path: '/tasks', label: '任务中心', desc: '创建与监控任务', icon: LayoutDashboard, badge: runningCount.value },
  { path: '/files', label: '文件库', desc: '浏览与导出成果', icon: FolderOpen, badge: 0 },
  { path: '/accounts', label: '账号池', desc: '凭据与额度管理', icon: Users, badge: 0 },
  { path: '/settings', label: '系统设置', desc: '代理与引擎配置', icon: Settings, badge: 0 },
])

const engineBadge = computed(() => {
  if (!runtime.value) return '初始化引擎…'
  return 'Rust · Pdfium Native'
})
</script>

<template>
  <aside class="app-sidebar">
    <div class="sidebar-brand" role="banner" @click="router.push('/tasks')">
      <div class="brand-emblem">
        <Layers :size="20" />
      </div>
      <div class="brand-copy">
        <h1>试卷下载器</h1>
        <span>STZY Desktop Studio</span>
      </div>
    </div>

    <div class="sidebar-group-label">工作空间</div>
    <nav class="sidebar-nav" aria-label="主导航">
      <button
        v-for="item in primaryNavItems"
        :key="item.path"
        type="button"
        class="sidebar-nav-item"
        :class="{ active: route.path.startsWith(item.path) }"
        @click="router.push(item.path)"
      >
        <span class="sidebar-nav-icon">
          <component :is="item.icon" :size="18" />
        </span>
        <span class="sidebar-nav-text">
          <strong>{{ item.label }}</strong>
          <small>{{ item.desc }}</small>
        </span>
        <span v-if="item.badge > 0" class="sidebar-nav-badge mono">{{ item.badge }}</span>
      </button>
    </nav>

    <div class="sidebar-footer">
      <button
        type="button"
        class="sidebar-console-btn"
        :class="{ active: footerExpanded }"
        @click="toggleFooter"
      >
        <Terminal :size="15" />
        <span>实时运行控制台</span>
        <span class="console-state">{{ footerExpanded ? '已展开' : '折叠' }}</span>
      </button>

      <div class="sidebar-engine-card">
        <div class="engine-head">
          <ShieldCheck :size="15" class="engine-icon" />
          <strong>{{ engineBadge }}</strong>
        </div>
        <p>本地离线存储 · AES-256 凭据保险箱</p>
      </div>
    </div>
  </aside>

  <nav class="mobile-bottom-nav" aria-label="移动端主导航">
    <button
      v-for="item in primaryNavItems"
      :key="item.path"
      type="button"
      class="mobile-bottom-nav-item"
      :class="{ active: route.path.startsWith(item.path) }"
      @click="router.push(item.path)"
    >
      <component :is="item.icon" :size="18" />
      <span>{{ item.label }}</span>
    </button>
  </nav>
</template>
