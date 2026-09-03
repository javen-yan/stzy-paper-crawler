<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { FolderOpen, LogOut, RefreshCw, Settings, TerminalSquare, Users } from 'lucide-vue-next'
import { useAuth } from '../../composables/useAuth'
import { useRuntime } from '../../composables/useRuntime'
import { useToast } from '../../composables/useToast'
import ProxyStatusPopover from './ProxyStatusPopover.vue'

const route = useRoute()
const router = useRouter()
const { logout } = useAuth()
const { runtime } = useRuntime()
const toast = useToast()

const navItems = [
  { path: '/tasks', label: '任务中心', icon: TerminalSquare },
  { path: '/files', label: '文件库', icon: FolderOpen },
  { path: '/accounts', label: '账号池', icon: Users },
  { path: '/settings', label: '设置', icon: Settings },
]

const runtimeLabel = computed(() => {
  if (!runtime.value) return '加载中'
  return runtime.value.mode === 'server' ? `Server · ${runtime.value.host}:${runtime.value.port}` : 'GUI · 127.0.0.1'
})
const showLogout = computed(() => runtime.value?.mode === 'server')

async function handleLogout() {
  await logout()
  toast.success('已退出')
}
</script>

<template>
  <header class="app-header">
    <div class="header-brand">
      <TerminalSquare :size="24" class="brand-icon" />
      <div>
        <h1>试卷下载器</h1>
        <span>stzy · worker console</span>
      </div>
    </div>

    <nav class="header-nav" aria-label="主导航">
      <button
        v-for="item in navItems"
        :key="item.path"
        class="header-nav-item"
        :class="{ active: route.path.startsWith(item.path) }"
        @click="router.push(item.path)"
      >
        <component :is="item.icon" :size="17" />
        <span>{{ item.label }}</span>
      </button>
    </nav>

    <div class="header-tools">
      <el-tag round class="runtime-pill">{{ runtimeLabel }}</el-tag>
      <ProxyStatusPopover />
      <span class="header-tool-divider" aria-hidden="true" />
      <el-tooltip content="刷新当前页面" placement="bottom">
        <el-button class="icon-tool-button" :icon="RefreshCw" circle aria-label="刷新当前页面" @click="$router.go(0)" />
      </el-tooltip>
      <el-tooltip v-if="showLogout" content="退出登录" placement="bottom">
        <el-button class="icon-tool-button" :icon="LogOut" circle aria-label="退出登录" @click="handleLogout" />
      </el-tooltip>
    </div>
  </header>
</template>

<style scoped>
.brand-icon {
  color: var(--app-primary);
  filter: drop-shadow(0 0 8px rgba(97, 175, 239, 0.6));
}
</style>
