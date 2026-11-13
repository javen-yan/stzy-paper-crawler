<script setup lang="ts">
import { Sparkles } from 'lucide-vue-next'

defineProps<{ title: string; description?: string; actionText?: string }>()
defineEmits<{ action: [] }>()
</script>

<template>
  <div class="empty-state">
    <span class="empty-glyph"><Sparkles :size="22" /></span>
    <h3>{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <el-button v-if="actionText" type="primary" @click="$emit('action')">{{ actionText }}</el-button>
  </div>
</template>

<style scoped>
.empty-glyph {
  display: inline-grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 14px;
  color: var(--app-primary);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(14, 165, 233, 0.12));
  border: 1px solid rgba(129, 140, 248, 0.28);
  box-shadow: 0 8px 24px -6px rgba(99, 102, 241, 0.35);
  margin-bottom: 14px;
}
</style>
