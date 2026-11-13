<script setup lang="ts">
import { computed } from 'vue'
import { Activity, AlertTriangle, CheckCircle2, Layers } from 'lucide-vue-next'
import type { Task } from '../../types/tasks'

export type TaskQuickFilter = 'all' | 'active' | 'completed' | 'attention' | 'archived'

const props = defineProps<{
  tasks: Task[]
  modelValue?: TaskQuickFilter
}>()

const emit = defineEmits<{
  'update:modelValue': [value: TaskQuickFilter]
}>()

const cards = computed(() => [
  {
    key: 'all' as TaskQuickFilter,
    label: '全部任务',
    value: props.tasks.length,
    icon: Layers,
    tone: 'idle',
  },
  {
    key: 'active' as TaskQuickFilter,
    label: '进行中 / 排队',
    value: props.tasks.filter((task) => ['running', 'queued', 'pausing'].includes(task.status)).length,
    icon: Activity,
    tone: 'active',
  },
  {
    key: 'completed' as TaskQuickFilter,
    label: '已完成',
    value: props.tasks.filter((task) => task.status === 'completed').length,
    icon: CheckCircle2,
    tone: 'success',
  },
  {
    key: 'attention' as TaskQuickFilter,
    label: '异常 / 已暂停',
    value: props.tasks.filter((task) =>
      ['failed', 'auth_expired', 'interrupted', 'partial_completed', 'paused'].includes(task.status),
    ).length,
    icon: AlertTriangle,
    tone: 'danger',
  },
])
</script>

<template>
  <div class="summary-grid">
    <button
      v-for="card in cards"
      :key="card.key"
      type="button"
      class="summary-card"
      :class="{ 'is-active': modelValue === card.key }"
      :data-tone="card.tone"
      @click="emit('update:modelValue', card.key)"
    >
      <div class="summary-card-top">
        <span class="summary-label">{{ card.label }}</span>
        <span class="summary-icon">
          <component :is="card.icon" :size="16" />
        </span>
      </div>
      <strong class="summary-value">{{ card.value }}</strong>
    </button>
  </div>
</template>

<style scoped>
.summary-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  border-radius: var(--app-radius);
  border: 1px solid var(--app-border);
  background: linear-gradient(165deg, rgba(24, 34, 56, 0.78) 0%, rgba(15, 22, 36, 0.9) 100%);
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease, background-color 160ms ease;
}

.summary-card:hover {
  transform: translateY(-1px);
  border-color: var(--app-border-strong);
}

.summary-card.is-active {
  border-color: rgba(129, 140, 248, 0.72);
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.28), var(--app-card-shadow);
}

.summary-card-top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.summary-label {
  color: var(--app-muted);
  font-size: 12.5px;
  font-weight: 550;
}

.summary-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(129, 140, 248, 0.25);
  background: var(--app-primary-soft);
  color: var(--app-primary);
}

.summary-value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.08;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  color: var(--app-text);
}

.summary-card[data-tone="active"] .summary-value {
  color: #a5b4fc;
}

.summary-card[data-tone="success"] .summary-icon {
  color: var(--app-accent);
  border-color: rgba(52, 211, 153, 0.28);
  background: var(--app-accent-soft);
}

.summary-card[data-tone="success"] .summary-value {
  color: var(--app-accent);
}

.summary-card[data-tone="danger"] .summary-icon {
  color: var(--app-danger);
  border-color: rgba(251, 113, 133, 0.28);
  background: var(--app-danger-soft);
}

.summary-card[data-tone="danger"] .summary-value {
  color: var(--app-danger);
}

.summary-card[data-tone="idle"] .summary-icon {
  color: var(--app-muted);
  border-color: var(--app-border);
  background: rgba(148, 163, 184, 0.08);
}
</style>
