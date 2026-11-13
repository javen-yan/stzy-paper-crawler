<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { PublicSettings } from '../../types/settings'

const props = defineProps<{ settings: PublicSettings; saving?: boolean }>()
const emit = defineEmits<{ save: [payload: Partial<PublicSettings>] }>()

const form = reactive({
  preview_max_pages: 300,
  preview_timeout_seconds: 45,
})

watch(
  () => props.settings,
  (settings) => {
    form.preview_max_pages = Number(settings.preview_max_pages || 300)
    form.preview_timeout_seconds = Number(settings.preview_timeout_seconds || 45)
  },
  { immediate: true },
)
</script>

<template>
  <el-card shadow="never">
    <template #header>预览限制</template>
    <el-form label-position="top">
      <el-form-item label="PDF 最大预览页数">
        <el-input-number v-model="form.preview_max_pages" :min="1" :max="500" />
      </el-form-item>
      <el-form-item label="转换超时秒数">
        <el-input-number v-model="form.preview_timeout_seconds" :min="5" :max="120" />
      </el-form-item>
      <el-button type="primary" :loading="saving" @click="$emit('save', { ...form })">保存预览设置</el-button>
    </el-form>
  </el-card>
</template>
