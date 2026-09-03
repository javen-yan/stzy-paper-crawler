<script setup lang="ts">
import { Terminal } from 'lucide-vue-next'

defineProps<{ title: string; description?: string; actionText?: string }>()
defineEmits<{ action: [] }>()
</script>

<template>
  <div class="empty-state">
    <span class="empty-glyph"><Terminal :size="22" /></span>
    <h3>{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <el-button v-if="actionText" type="primary" @click="$emit('action')">{{ actionText }}</el-button>
  </div>
</template>

<style scoped>
.empty-glyph {
  display: inline-grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 8px;
  color: var(--app-primary);
  background: var(--app-primary-soft);
  border: 1px solid rgba(97, 175, 239, 0.3);
  margin-bottom: 12px;
}
</style>
