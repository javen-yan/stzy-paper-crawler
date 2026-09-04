<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from '../../types/tasks'

const props = defineProps<{ task: Task }>()

const stats = computed(() => props.task.stats || {})

// estimate 模式按“条件组合”计，crawl 模式按“资源（试卷）”计
const total = computed(() => {
  if (props.task.mode === 'estimate') return Number(stats.value.total_combos || 0)
  return Number(stats.value.resources_total || stats.value.resources_seen || 0)
})

const done = computed(() => {
  if (props.task.mode === 'estimate') return Number(stats.value.completed_combos || 0)
  return Number(stats.value.resources_processed || stats.value.resources_completed || 0)
})

const completed = computed(() => Number(stats.value.resources_completed || 0))
const failed = computed(() => Number(stats.value.failed || 0))
const filtered = computed(() => Number(stats.value.filtered_skipped || 0))

const percentage = computed(() => {
  if (!total.value) return props.task.status === 'completed' ? 100 : 0
  return Math.max(0, Math.min(100, Math.round((done.value / total.value) * 100)))
})

const running = computed(() => props.task.status === 'running')

const tone = computed(() => {
  if (props.task.status === 'completed') return 'success'
  if (['failed', 'auth_expired', 'cancelled', 'interrupted'].includes(props.task.status)) return 'danger'
  if (['paused', 'pausing', 'partial_completed'].includes(props.task.status)) return 'warning'
  if (props.task.status === 'running') return 'active'
  return 'idle'
})
</script>

<template>
  <div class="task-progress" :data-tone="tone">
    <div class="progress-track">
      <div
        class="progress-fill"
        :class="{ 'is-animated': running }"
        :style="{ width: `${percentage}%` }"
      />
    </div>
    <div class="progress-meta">
      <span class="progress-count" v-if="total">
        已处理 {{ done }}/{{ total }}
        <small v-if="completed || failed || filtered">完成 {{ completed }}，失败 {{ failed }}，地区过滤 {{ filtered }}</small>
      </span>
      <span class="progress-pct">{{ percentage }}%</span>
    </div>
  </div>
</template>

<style scoped>
.task-progress {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.progress-track {
  height: 8px;
  border-radius: 4px;
  background: var(--app-bg);
  border: 1px solid var(--app-border);
  overflow: hidden;
  position: relative;
}

.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #3e7fbf, #61afef);
  box-shadow: 0 0 10px rgba(97, 175, 239, 0.6);
  transition: width 400ms cubic-bezier(0.4, 0, 0.2, 1);
}

.progress-fill.is-animated {
  background: repeating-linear-gradient(
    45deg,
    #3e7fbf,
    #3e7fbf 6px,
    #61afef 6px,
    #61afef 12px
  );
  background-size: 200% 100%;
  animation: scan 1s linear infinite;
}

[data-tone="success"] .progress-fill {
  background: linear-gradient(90deg, #7cb363, #98c379);
  box-shadow: 0 0 10px rgba(152, 195, 121, 0.6);
}

[data-tone="warning"] .progress-fill {
  background: linear-gradient(90deg, #c8a157, #e5c07b);
  box-shadow: 0 0 10px rgba(229, 192, 123, 0.6);
}

[data-tone="danger"] .progress-fill {
  background: linear-gradient(90deg, #be505a, #e06c75);
  box-shadow: 0 0 10px rgba(224, 108, 117, 0.6);
}

[data-tone="idle"] .progress-fill {
  background: linear-gradient(90deg, #475569, #64748b);
  box-shadow: none;
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-family: var(--app-mono);
  font-size: 11.5px;
  color: var(--app-muted);
}

.progress-count {
  color: var(--app-text);
}

.progress-count small {
  margin-left: 6px;
  color: var(--app-muted);
  font-family: var(--app-font);
}

.progress-pct {
  color: var(--app-primary);
}

[data-tone="success"] .progress-pct {
  color: var(--app-accent);
}

[data-tone="warning"] .progress-pct {
  color: var(--app-warning);
}

[data-tone="danger"] .progress-pct {
  color: var(--app-danger);
}

@keyframes scan {
  from {
    background-position: 0 0;
  }
  to {
    background-position: 200% 0;
  }
}
</style>
