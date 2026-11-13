<script setup lang="ts">
defineProps<{ message: string; retryText?: string }>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <el-alert :title="message" type="error" show-icon :closable="false">
    <template #default>
      <el-button v-if="retryText" text type="primary" @click="$emit('retry')">{{ retryText }}</el-button>
    </template>
  </el-alert>
</template>
