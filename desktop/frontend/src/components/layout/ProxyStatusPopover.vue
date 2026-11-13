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
  if (!status.value) return '检测中'
  if (status.value.proxy_mode === 'fixed') return '固定池'
  if (status.value.proxy_mode === 'api') return status.value.proxy_provider === 'shenlong' ? '神龙代理' : 'API代理'
  return '直连模式'
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
  if (!status.value) return '代理池状态同步中'
  const available = status.value.available_proxy_count || 0
  const leased = status.value.leased_proxy_count || 0
  const cooldown = status.value.cooldown_proxy_count || 0
  return `空闲 ${available} · 租用 ${leased} · 冷却 ${cooldown}`
})

const myIpLabel = computed(() => {
  if (!status.value) return '检测中'
  if (status.value.my_ip) return status.value.my_ip
  return '离线/未知'
})

const myIpSummary = computed(() => {
  if (!status.value) return '正在检测当前本机出口 IP'
  if (status.value.my_ip) return `当前本机出口 IP：${status.value.my_ip}`
  return status.value.my_ip_status?.error || '公共 IP 检测源暂不可用'
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
    // 顶栏状态为辅助展示，失败时静默保留上次状态
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
  }, 3200)
})

onUnmounted(() => {
  polling.stop()
  if (rotateTimer) window.clearInterval(rotateTimer)
})
</script>

<template>
  <div class="header-status-strip" aria-label="网络与调度状态">
    <el-tooltip content="当前运行中的采集/预估任务数" placement="bottom">
      <span class="status-chip" :data-tone="(status?.running_task_count || 0) > 0 ? 'active' : 'idle'">
        <Activity :size="14" />
        <span>活跃</span>
        <strong class="mono">{{ status?.running_task_count || 0 }}</strong>
      </span>
    </el-tooltip>

    <el-tooltip :content="proxySummary" placement="bottom">
      <button class="status-chip status-chip-button" type="button" aria-label="打开代理设置" @click="goSettings">
        <ServerCog :size="14" />
        <span>{{ modeLabel }}</span>
        <strong v-if="status?.proxy_mode && status.proxy_mode !== 'off'" class="mono">
          {{ status?.leased_proxy_count || 0 }}/{{ status?.target_proxy_count || 0 }}
        </strong>
      </button>
    </el-tooltip>

    <el-tooltip :content="myIpSummary" placement="bottom">
      <span class="status-chip status-chip-wide" :data-tone="status?.my_ip ? 'ready' : 'idle'">
        <Globe2 :size="14" />
        <span>出口</span>
        <strong class="mono">{{ myIpLabel }}</strong>
      </span>
    </el-tooltip>

    <el-tooltip
      v-if="status?.proxy_mode && status.proxy_mode !== 'off'"
      :content="currentProxy ? `${currentProxy.source} · ${currentProxy.status}` : '等待拉取代理节点'"
      placement="bottom"
    >
      <button
        class="status-chip status-chip-wide proxy-rotator"
        type="button"
        :data-tone="statusTone(currentProxy?.status)"
        aria-label="代理池节点，点击管理"
        @click="goSettings"
      >
        <RadioTower :size="14" />
        <transition name="proxy-slide" mode="out-in">
          <strong :key="currentProxy?.id || 'empty'" class="mono">{{ currentProxy?.address || '待分配节点' }}</strong>
        </transition>
      </button>
    </el-tooltip>
  </div>
</template>

<style scoped>
.header-status-strip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.status-chip {
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 184px;
  padding: 0 11px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.65);
  color: var(--app-muted);
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
  transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease;
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
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-chip-button,
.proxy-rotator {
  font: inherit;
  cursor: pointer;
}

.status-chip-button:hover,
.proxy-rotator:hover {
  border-color: rgba(129, 140, 248, 0.45);
  background: var(--app-primary-soft);
}

.status-chip-wide {
  max-width: 210px;
}

.status-chip[data-tone='active'],
.proxy-rotator[data-tone='active'] {
  border-color: rgba(99, 102, 241, 0.42);
  background: rgba(99, 102, 241, 0.12);
}

.status-chip[data-tone='ready'] svg {
  color: var(--app-accent);
}

.proxy-rotator[data-tone='warning'] {
  border-color: rgba(245, 158, 11, 0.4);
}

.status-chip[data-tone='danger'],
.proxy-rotator[data-tone='danger'] {
  border-color: rgba(244, 63, 94, 0.4);
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

@media (max-width: 1180px) {
  .status-chip-wide {
    max-width: 152px;
  }
}

@media (max-width: 760px) {
  .header-status-strip {
    display: none;
  }
}
</style>
