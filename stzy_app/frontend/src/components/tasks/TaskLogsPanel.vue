<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import type { LogLine } from '../../types/tasks'

const props = defineProps<{ logs: LogLine[] }>()
const emit = defineEmits<{ refresh: [] }>()
const logBox = ref<HTMLElement | null>(null)

function scrollToBottom() {
  nextTick(() => {
    if (!logBox.value) return
    logBox.value.scrollTop = logBox.value.scrollHeight
  })
}

function refreshAndFollow() {
  emit('refresh')
  scrollToBottom()
}

watch(
  () => props.logs.length,
  () => scrollToBottom(),
  { flush: 'post', immediate: true },
)

onMounted(scrollToBottom)
</script>

<template>
  <el-card shadow="never" class="task-logs-card">
    <template #header>
      <div class="card-header">
        <span>运行日志</span>
        <span class="log-count mono">最近 {{ logs.length }} 条</span>
        <el-button size="small" @click="refreshAndFollow">刷新</el-button>
      </div>
    </template>
    <div v-if="logs.length" ref="logBox" class="log-box task-log-box" aria-live="polite">
      <p v-for="line in logs" :key="line.id" :class="`log ${line.level}`">
        <time>{{ line.created_at }}</time>
        <strong class="mono">[{{ line.level || 'info' }}]</strong>
        <span>{{ line.message }}</span>
      </p>
    </div>
    <el-empty v-else description="暂无日志" />
  </el-card>
</template>

<style scoped>
.log-count {
  color: var(--app-primary);
  font-size: 12px;
  padding: 2px 10px;
  border: 1px solid rgba(97, 175, 239, 0.3);
  border-radius: 999px;
  background: var(--app-primary-soft);
}

.task-log-box {
  max-height: clamp(360px, calc(100dvh - 420px), 640px);
  min-height: 320px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 12px;
  scroll-behavior: smooth;
}

@media (max-width: 768px) {
  .task-log-box {
    max-height: 58dvh;
    min-height: 280px;
  }
}
</style>
