<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  CheckCircle2,
  FolderOpen,
  FolderOutput,
  Layers,
  LayoutList,
  Settings,
  Sparkles,
  TriangleAlert,
  Users,
} from 'lucide-vue-next'
import { openExternalUrl, openLocalPath } from '../../api/local'
import { useRuntime } from '../../composables/useRuntime'
import { useTasks } from '../../composables/useTasks'
import { useToast } from '../../composables/useToast'
import { useUpdater } from '../../composables/useUpdater'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const { hasOfficeCore, libreOfficeUrl } = useRuntime()
const { tasks } = useTasks()
const { currentVersion, hasUpdate, updateInfo, checking, checkForUpdates, openUpdateDialog } = useUpdater()

const runningCount = computed(() => tasks.value.filter((task) => task.status === 'running').length)

const primaryNavItems = computed(() => [
  { path: '/tasks', label: '任务管理', icon: LayoutList, badge: runningCount.value },
  { path: '/files', label: '本地文件', icon: FolderOpen, badge: 0 },
  { path: '/accounts', label: '账号管理', icon: Users, badge: 0 },
  { path: '/settings', label: '系统设置', icon: Settings, badge: 0 },
])

async function openOutputRoot() {
  try {
    await openLocalPath('')
  } catch (error) {
    toast.error(error, '打开输出目录失败')
  }
}

async function handleCoreClick() {
  if (hasOfficeCore.value) {
    router.push('/settings')
    return
  }
  try {
    await openExternalUrl(libreOfficeUrl.value)
  } catch (error) {
    toast.error(error, '打开下载链接失败')
  }
}
</script>

<template>
  <aside class="app-sidebar">
    <div class="sidebar-brand" role="banner" @click="router.push('/tasks')">
      <div class="brand-emblem">
        <Layers :size="19" />
      </div>
      <div class="brand-copy">
        <h1>试卷下载器</h1>
        <button
          type="button"
          class="version-btn"
          title="点击检查软件更新"
          @click.stop="hasUpdate ? openUpdateDialog() : checkForUpdates({ silent: false, openIfAvailable: true })"
        >
          <span>v{{ currentVersion }}</span>
          <span v-if="checking" class="ver-dot checking">检查中…</span>
          <span v-else-if="hasUpdate" class="ver-dot new">有新版</span>
        </button>
      </div>
    </div>

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
          <component :is="item.icon" :size="17" />
        </span>
        <span class="sidebar-nav-text">
          <strong>{{ item.label }}</strong>
        </span>
        <span v-if="item.badge > 0" class="sidebar-nav-badge mono">{{ item.badge }}</span>
      </button>
    </nav>

    <div class="sidebar-footer">
      <button v-if="hasUpdate" type="button" class="sidebar-update-btn" @click="openUpdateDialog">
        <Sparkles :size="14" />
        <span>发现新版本 v{{ updateInfo?.version }} · 点击升级</span>
      </button>

      <button type="button" class="sidebar-console-btn" @click="openOutputRoot">
        <FolderOutput :size="15" />
        <span>打开下载目录</span>
      </button>

      <button
        type="button"
        class="sidebar-core-status"
        :class="{ missing: !hasOfficeCore }"
        @click="handleCoreClick"
      >
        <CheckCircle2 v-if="hasOfficeCore" :size="14" class="core-ok-icon" />
        <TriangleAlert v-else :size="14" class="core-warn-icon" />
        <span>{{ hasOfficeCore ? '文档转换核心已就绪' : '未安装 LibreOffice · 点击下载' }}</span>
      </button>
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

<style scoped>
.version-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 6px;
  margin: 2px 0 0 -6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--app-muted);
  font-size: 11.5px;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.version-btn:hover {
  background: rgba(148, 163, 184, 0.12);
  color: var(--app-text);
}

.ver-dot {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10.5px;
  font-family: inherit;
  font-weight: 600;
  line-height: 1.4;
}

.ver-dot.checking {
  background: rgba(56, 189, 248, 0.14);
  color: #7dd3fc;
}

.ver-dot.new {
  background: rgba(99, 102, 241, 0.22);
  border: 1px solid rgba(129, 140, 248, 0.4);
  color: #c7d2fe;
}

.sidebar-update-btn {
  width: 100%;
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 11px;
  border-radius: 9px;
  border: 1px solid rgba(129, 140, 248, 0.45);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(56, 189, 248, 0.15));
  color: #e0e7ff;
  font-size: 12px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition: border-color 150ms ease, transform 150ms ease, filter 150ms ease;
}

.sidebar-update-btn:hover {
  border-color: rgba(165, 180, 252, 0.72);
  filter: brightness(1.08);
}

.sidebar-core-status {
  width: 100%;
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 11px;
  border-radius: 9px;
  border: 1px solid var(--app-border);
  background: rgba(15, 23, 42, 0.5);
  color: var(--app-muted);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  transition: border-color 150ms ease, color 150ms ease, background-color 150ms ease;
}

.sidebar-core-status:hover {
  border-color: rgba(148, 163, 184, 0.35);
  color: var(--app-text);
}

.sidebar-core-status.missing {
  border-color: rgba(245, 158, 11, 0.38);
  background: rgba(245, 158, 11, 0.1);
  color: #fcd34d;
}

.core-ok-icon {
  color: var(--app-accent);
  flex: 0 0 auto;
}

.core-warn-icon {
  color: var(--app-warning);
  flex: 0 0 auto;
}
</style>
