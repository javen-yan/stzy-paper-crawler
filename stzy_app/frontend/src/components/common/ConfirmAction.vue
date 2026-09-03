<script setup lang="ts">
import { ElMessageBox } from 'element-plus'

const props = defineProps<{
  title: string
  message: string
  type?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  disabled?: boolean
}>()
const emit = defineEmits<{ confirm: [] }>()

async function confirm() {
  await ElMessageBox.confirm(props.message, props.title, {
    confirmButtonText: '确认',
    cancelButtonText: '取消',
    type: props.type === 'danger' ? 'warning' : props.type,
  })
  emit('confirm')
}
</script>

<template>
  <el-button :type="type" :disabled="disabled" @click="confirm">
    <slot />
  </el-button>
</template>
