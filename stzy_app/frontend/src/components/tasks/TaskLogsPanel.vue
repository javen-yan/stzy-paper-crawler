<script setup lang="ts">
import type { LogLine } from '../../types/tasks'

defineProps<{ logs: LogLine[] }>()
defineEmits<{ refresh: [] }>()
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span>运行日志</span>
        <span class="log-count mono">{{ logs.length }} 条</span>
        <el-button size="small" @click="$emit('refresh')">刷新</el-button>
      </div>
    </template>
    <div v-if="logs.length" class="log-box" aria-live="polite">
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
</style>
