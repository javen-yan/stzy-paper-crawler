<script setup lang="ts">
import { computed } from 'vue'
import { Activity, AlertTriangle, CheckCircle2, Clock } from 'lucide-vue-next'
import type { Task } from '../../types/tasks'

const props = defineProps<{ tasks: Task[] }>()

const cards = computed(() => [
  { key: 'running', label: '运行中', value: props.tasks.filter((task) => task.status === 'running').length, icon: Activity, tone: 'active' },
  { key: 'queued', label: '排队中', value: props.tasks.filter((task) => task.status === 'queued').length, icon: Clock, tone: 'idle' },
  { key: 'completed', label: '已完成', value: props.tasks.filter((task) => task.status === 'completed').length, icon: CheckCircle2, tone: 'success' },
  {
    key: 'attention',
    label: '需处理',
    value: props.tasks.filter((task) => ['failed', 'auth_expired', 'interrupted', 'partial_completed'].includes(task.status)).length,
    icon: AlertTriangle,
    tone: 'danger',
  },
])
</script>

<template>
  <div class="summary-grid">
    <el-card v-for="card in cards" :key="card.key" shadow="never" class="summary-card" :data-tone="card.tone">
      <span class="summary-icon">
        <component :is="card.icon" :size="20" />
      </span>
      <span class="summary-content">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </span>
    </el-card>
  </div>
</template>

<style scoped>
.summary-card[data-tone="active"] .summary-icon {
  color: var(--app-primary);
  border-color: rgba(97, 175, 239, 0.4);
  background: var(--app-primary-soft);
  box-shadow: 0 0 14px rgba(97, 175, 239, 0.25);
}

.summary-card[data-tone="success"] .summary-icon {
  color: var(--app-accent);
  border-color: rgba(152, 195, 121, 0.4);
  background: rgba(152, 195, 121, 0.12);
}

.summary-card[data-tone="success"] strong {
  color: var(--app-accent);
  text-shadow: 0 0 16px rgba(152, 195, 121, 0.45);
}

.summary-card[data-tone="danger"] .summary-icon {
  color: var(--app-danger);
  border-color: rgba(224, 108, 117, 0.4);
  background: rgba(224, 108, 117, 0.12);
}

.summary-card[data-tone="danger"] strong {
  color: var(--app-danger);
  text-shadow: 0 0 16px rgba(224, 108, 117, 0.45);
}

.summary-card[data-tone="idle"] .summary-icon {
  color: var(--app-muted);
  border-color: var(--app-border);
  background: var(--app-bg-2);
}

.summary-card[data-tone="idle"] strong {
  color: var(--app-text);
  text-shadow: none;
}
</style>
