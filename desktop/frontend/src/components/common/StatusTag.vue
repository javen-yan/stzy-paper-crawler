<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string; label?: string }>()

const tone = computed(() => {
  if (props.status === 'completed') return 'success'
  if (['failed', 'auth_expired', 'cancelled', 'interrupted'].includes(props.status)) return 'danger'
  if (['paused', 'pausing', 'partial_completed'].includes(props.status)) return 'warning'
  if (props.status === 'running') return 'active'
  return 'idle'
})
</script>

<template>
  <span class="status-tag" :data-tone="tone">
    <span class="status-dot" :class="{ pulse: status === 'running' }" aria-hidden="true" />
    {{ label || status }}
  </span>
</template>

<style scoped>
.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 10px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.08);
  color: var(--app-muted);
  font-size: 12px;
  font-weight: 550;
  line-height: 1;
  white-space: nowrap;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
}

.status-dot.pulse {
  animation: pulse 1.4s ease-in-out infinite;
}

[data-tone="active"] {
  color: #a5b4fc;
  border-color: rgba(129, 140, 248, 0.35);
  background: rgba(99, 102, 241, 0.16);
}

[data-tone="active"] .status-dot {
  box-shadow: 0 0 8px rgba(129, 140, 248, 0.9);
}

[data-tone="success"] {
  color: var(--app-accent);
  border-color: rgba(52, 211, 153, 0.32);
  background: var(--app-accent-soft);
}

[data-tone="warning"] {
  color: var(--app-warning);
  border-color: rgba(251, 191, 36, 0.32);
  background: var(--app-warning-soft);
}

[data-tone="danger"] {
  color: var(--app-danger);
  border-color: rgba(251, 113, 133, 0.32);
  background: var(--app-danger-soft);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.35;
    transform: scale(0.85);
  }
}
</style>
