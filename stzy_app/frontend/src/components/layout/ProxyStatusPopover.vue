<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, Globe2, RadioTower, ServerCog } from 'lucide-vue-next'
import { fetchProxyStatus } from '../../api/proxy'
import { usePolling } from '../../composables/usePolling'
import type { ProxyStatus, ProxyStatusItem } from '../../types/proxy'

const router = useRouter()
const status = ref<ProxyStatus | null>(null)
const proxyIndex = ref(0)
let rotateTimer: number | undefined

const modeLabel = computed(() => {
  if (!status.value) return '加载中'
  if (status.value.proxy_mode === 'fixed') return '固定池'
  if (status.value.proxy_mode === 'api') return status.value.proxy_provider === 'shenlong' ? '神龙HTTP' : 'API代理'
  return '未代理'
})

const proxyItems = computed<ProxyStatusItem[]>(() => {
  const items = status.value?.items || []
  return [...items].sort((left, right) => statusWeight(left.status) - statusWeight(right.status))
})

const currentProxy = computed(() => {
  if (!proxyItems.value.length) return null
  return proxyItems.value[proxyIndex.value % proxyItems.value.length]
})

const proxySummary = computed(() => {
  if (!status.value) return '代理池加载中'
  const available = status.value.available_proxy_count || 0
  const leased = status.value.leased_proxy_count || 0
  const cooldown = status.value.cooldown_proxy_count || 0
  return `空闲 ${available} · 使用 ${leased} · 冷却 ${cooldown}`
})

const myIpLabel = computed(() => {
  if (!status.value) return '检测中'
  if (status.value.my_ip) return status.value.my_ip
  return '检测失败'
})

const myIpSummary = computed(() => {
  if (!status.value) return '正在检测当前本机出口 IP'
  if (status.value.my_ip) return `当前本机出口 IP：${status.value.my_ip}`
  return status.value.my_ip_status?.error || '公共 IP 检测源暂时不可用'
})

function statusWeight(value?: string) {
  if (value === '使用中') return 0
  if (value === '空闲') return 1
  if (value === '冷却中') return 2
  return 3
}

function statusTone(value?: string) {
  if (value === '使用中') return 'active'
  if (value === '空闲') return 'ready'
  if (value === '冷却中') return 'warning'
  if (value === '失效') return 'danger'
  return 'idle'
}

async function refreshStatus() {
  try {
    status.value = await fetchProxyStatus()
    if (proxyIndex.value >= proxyItems.value.length) proxyIndex.value = 0
  } catch {
    // Header 状态是辅助信息，失败时保留旧值，避免打断用户主流程。
  }
}

async function goSettings() {
  await router.push('/settings')
}

const polling = usePolling(refreshStatus, 15000, { hiddenIntervalMs: 60000 })

onMounted(() => {
  refreshStatus()
  polling.start()
  rotateTimer = window.setInterval(() => {
    if (proxyItems.value.length > 1) proxyIndex.value = (proxyIndex.value + 1) % proxyItems.value.length
  }, 3000)
})

onUnmounted(() => {
  polling.stop()
  if (rotateTimer) window.clearInterval(rotateTimer)
})
</script>

<template>
  <div class="header-status-strip" aria-label="系统状态">
    <el-tooltip content="运行中的任务数量" placement="bottom">
      <span class="status-chip">
        <Activity :size="15" />
        <span>任务</span>
        <strong class="mono">{{ status?.running_task_count || 0 }}</strong>
      </span>
    </el-tooltip>

    <el-tooltip :content="proxySummary" placement="bottom">
      <button class="status-chip status-chip-button" type="button" aria-label="打开代理设置" @click="goSettings">
        <ServerCog :size="15" />
        <span>{{ modeLabel }}</span>
        <strong class="mono">{{ status?.leased_proxy_count || 0 }}/{{ status?.target_proxy_count || 0 }}</strong>
      </button>
    </el-tooltip>

    <el-tooltip :content="myIpSummary" placement="bottom">
      <span class="status-chip status-chip-wide" :data-tone="status?.my_ip ? 'ready' : status ? 'danger' : 'idle'">
        <Globe2 :size="15" />
        <span>我的IP</span>
        <strong class="mono">{{ myIpLabel }}</strong>
      </span>
    </el-tooltip>

    <el-tooltip :content="currentProxy ? `${currentProxy.source} · ${currentProxy.status}` : '暂无代理 IP'" placement="bottom">
      <button
        class="status-chip status-chip-wide proxy-rotator"
        type="button"
        :data-tone="statusTone(currentProxy?.status)"
        aria-label="代理池 IP，点击进入代理设置"
        @click="goSettings"
      >
        <RadioTower :size="15" />
        <span>代理IP</span>
        <transition name="proxy-slide" mode="out-in">
          <strong :key="currentProxy?.id || 'empty'" class="mono">{{ currentProxy?.address || '未配置代理' }}</strong>
        </transition>
      </button>
    </el-tooltip>
  </div>
</template>

<style scoped>
.header-status-strip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.status-chip {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 178px;
  padding: 0 10px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--app-surface) 92%, transparent);
  color: var(--app-muted);
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
}

.status-chip svg {
  color: var(--app-primary);
  flex: 0 0 auto;
}

.status-chip strong {
  min-width: 0;
  overflow: hidden;
  color: var(--app-text);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-chip-button {
  cursor: pointer;
}

.status-chip-button,
.proxy-rotator {
  font: inherit;
}

.status-chip-button:hover,
.proxy-rotator:hover {
  border-color: rgba(97, 175, 239, 0.48);
  background: var(--app-primary-soft);
}

.status-chip-wide {
  max-width: 220px;
}

.proxy-rotator {
  cursor: pointer;
}

.proxy-rotator[data-tone='active'] {
  border-color: rgba(152, 195, 121, 0.45);
}

.status-chip[data-tone='ready'] {
  border-color: rgba(152, 195, 121, 0.45);
}

.proxy-rotator[data-tone='warning'] {
  border-color: rgba(229, 192, 123, 0.45);
}

.status-chip[data-tone='danger'],
.proxy-rotator[data-tone='danger'] {
  border-color: rgba(224, 108, 117, 0.45);
}

.proxy-slide-enter-active,
.proxy-slide-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.proxy-slide-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

.proxy-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (max-width: 1280px) {
  .status-chip-wide {
    max-width: 150px;
  }
}

@media (max-width: 1100px) {
  .header-status-strip {
    flex: 0 0 auto;
    width: auto;
    max-width: max-content;
    justify-content: flex-start;
  }

  .status-chip {
    flex: 0 0 auto;
  }
}

@media (max-width: 760px) {
  .status-chip {
    max-width: 142px;
    min-height: 30px;
    padding: 0 9px;
  }

  .status-chip-wide {
    max-width: 156px;
  }
}
</style>
