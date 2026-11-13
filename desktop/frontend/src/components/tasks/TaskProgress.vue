<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from '../../types/tasks'

const props = defineProps<{ task: Task }>()

const stats = computed(() => props.task.stats || {})

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
      <span v-if="total" class="progress-count">
        已处理 <strong class="mono">{{ done }}/{{ total }}</strong>
        <small v-if="completed || failed || filtered">
          · 完成 {{ completed }} · 失败 {{ failed }}<template v-if="filtered"> · 过滤 {{ filtered }}</template>
        </small>
      </span>
      <span v-else class="progress-count muted">等待统计返回…</span>
      <span class="progress-pct mono">{{ percentage }}%</span>
    </div>
  </div>
</template>

<style scoped>
.task-progress {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.progress-track {
  height: 7px;
  border-radius: 999px;
  background: rgba(9, 13, 22, 0.85);
  border: 1px solid rgba(148, 163, 184, 0.12);
  overflow: hidden;
  position: relative;
}

.progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #6366f1 0%, #38bdf8 100%);
  transition: width 420ms cubic-bezier(0.22, 1, 0.36, 1);
  position: relative;
}

.progress-fill.is-animated::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.35) 50%,
    transparent 100%
  );
  animation: shimmer 1.6s ease-in-out infinite;
}

[data-tone="success"] .progress-fill {
  background: linear-gradient(90deg, #10b981 0%, #34d399 100%);
}

[data-tone="warning"] .progress-fill {
  background: linear-gradient(90deg, #f59e0b 0%, #fbbf24 100%);
}

[data-tone="danger"] .progress-fill {
  background: linear-gradient(90deg, #e11d48 0%, #fb7185 100%);
}

[data-tone="idle"] .progress-fill {
  background: linear-gradient(90deg, #475569 0%, #64748b 100%);
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--app-muted);
}

.progress-count {
  color: var(--app-text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-count.muted {
  color: var(--app-faint);
}

.progress-count strong {
  font-weight: 600;
}

.progress-count small {
  margin-left: 4px;
  color: var(--app-muted);
  font-size: 11.5px;
}

.progress-pct {
  flex: 0 0 auto;
  font-weight: 650;
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

@keyframes shimmer {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}
</style>
