<script setup lang="ts">
import { computed } from 'vue'
import { Activity, AlertTriangle, CheckCircle2, Clock } from 'lucide-vue-next'
import type { Task } from '../../types/tasks'

const props = defineProps<{ tasks: Task[] }>()

const cards = computed(() => [
  {
    key: 'running',
    label: '正在运行',
    caption: '实时并发下载中',
    value: props.tasks.filter((task) => task.status === 'running').length,
    icon: Activity,
    tone: 'active',
  },
  {
    key: 'queued',
    label: '等待调度',
    caption: '队列中待启动',
    value: props.tasks.filter((task) => task.status === 'queued').length,
    icon: Clock,
    tone: 'idle',
  },
  {
    key: 'completed',
    label: '已完成',
    caption: '已转换并归档本地',
    value: props.tasks.filter((task) => task.status === 'completed').length,
    icon: CheckCircle2,
    tone: 'success',
  },
  {
    key: 'attention',
    label: '需关注',
    caption: '异常或部分完成',
    value: props.tasks.filter((task) => ['failed', 'auth_expired', 'interrupted', 'partial_completed'].includes(task.status)).length,
    icon: AlertTriangle,
    tone: 'danger',
  },
])
</script>

<template>
  <div class="summary-grid">
    <article v-for="card in cards" :key="card.key" class="summary-card" :data-tone="card.tone">
      <div class="summary-card-top">
        <span class="summary-label">{{ card.label }}</span>
        <span class="summary-icon">
          <component :is="card.icon" :size="18" />
        </span>
      </div>
      <strong class="summary-value">{{ card.value }}</strong>
      <small class="summary-caption">{{ card.caption }}</small>
    </article>
  </div>
</template>

<style scoped>
.summary-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px 20px;
  border-radius: var(--app-radius);
  border: 1px solid var(--app-border);
  background: linear-gradient(165deg, rgba(24, 34, 56, 0.82) 0%, rgba(15, 22, 36, 0.92) 100%);
  box-shadow: var(--app-card-shadow);
  overflow: hidden;
  transition: transform 180ms cubic-bezier(0.22, 1, 0.36, 1), border-color 180ms ease, box-shadow 180ms ease;
}

.summary-card::after {
  content: "";
  position: absolute;
  top: -36px;
  right: -36px;
  width: 110px;
  height: 110px;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(129, 140, 248, 0.14), transparent 70%);
  pointer-events: none;
}

.summary-card:hover {
  transform: translateY(-2px);
  border-color: var(--app-border-strong);
  box-shadow: var(--app-glow-soft);
}

.summary-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.summary-label {
  color: var(--app-muted);
  font-size: 13px;
  font-weight: 550;
}

.summary-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(129, 140, 248, 0.25);
  background: var(--app-primary-soft);
  color: var(--app-primary);
}

.summary-value {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.08;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  color: var(--app-text);
}

.summary-caption {
  color: var(--app-faint);
  font-size: 12px;
}

.summary-card[data-tone="active"] {
  border-color: rgba(99, 102, 241, 0.28);
}

.summary-card[data-tone="active"] .summary-value {
  color: #a5b4fc;
}

.summary-card[data-tone="success"]::after {
  background: radial-gradient(circle, rgba(16, 185, 129, 0.14), transparent 70%);
}

.summary-card[data-tone="success"] .summary-icon {
  color: var(--app-accent);
  border-color: rgba(52, 211, 153, 0.28);
  background: var(--app-accent-soft);
}

.summary-card[data-tone="success"] .summary-value {
  color: var(--app-accent);
}

.summary-card[data-tone="danger"]::after {
  background: radial-gradient(circle, rgba(244, 63, 94, 0.14), transparent 70%);
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
