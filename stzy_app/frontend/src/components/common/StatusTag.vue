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
  gap: 7px;
  height: 24px;
  padding: 0 10px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-bg-2);
  color: var(--app-muted);
  font-family: var(--app-mono);
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentColor;
}

.status-dot.pulse {
  animation: pulse 1.2s ease-in-out infinite;
}

[data-tone="active"] {
  color: var(--app-primary);
  border-color: rgba(97, 175, 239, 0.4);
  background: var(--app-primary-soft);
}

[data-tone="active"] .status-dot {
  box-shadow: 0 0 8px var(--app-primary);
}

[data-tone="success"] {
  color: var(--app-accent);
  border-color: rgba(152, 195, 121, 0.4);
  background: rgba(152, 195, 121, 0.1);
}

[data-tone="warning"] {
  color: var(--app-warning);
  border-color: rgba(229, 192, 123, 0.4);
  background: rgba(229, 192, 123, 0.1);
}

[data-tone="danger"] {
  color: var(--app-danger);
  border-color: rgba(224, 108, 117, 0.4);
  background: rgba(224, 108, 117, 0.1);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
}
</style>
