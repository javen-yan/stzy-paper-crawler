<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { PublicSettings } from '../../types/settings'

const props = defineProps<{ settings: PublicSettings; saving?: boolean }>()
const emit = defineEmits<{ save: [payload: Partial<PublicSettings>] }>()

const form = reactive({
  max_active_tasks: 2,
  max_download_workers: 4,
  max_convert_workers: 2,
  max_export_workers: 1,
})

watch(
  () => props.settings,
  (settings) => {
    form.max_active_tasks = Number(settings.max_active_tasks || 2)
    form.max_download_workers = Number(settings.max_download_workers || 4)
    form.max_convert_workers = Number(settings.max_convert_workers || 2)
    form.max_export_workers = Number(settings.max_export_workers || 1)
  },
  { immediate: true },
)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span>并发控制</span>
      </div>
    </template>

    <el-form label-position="top" class="settings-form concurrency-settings-form">
      <div class="settings-grid two-columns">
        <el-form-item label="同时运行任务数">
          <el-input-number v-model="form.max_active_tasks" :min="1" :max="8" />
        </el-form-item>

        <el-form-item label="单个任务下载并发">
          <el-input-number v-model="form.max_download_workers" :min="1" :max="32" />
        </el-form-item>

        <el-form-item label="PDF 转图片进程数">
          <el-input-number v-model="form.max_convert_workers" :min="1" :max="8" />
        </el-form-item>

        <el-form-item label="ZIP 打包并发">
          <el-input-number v-model="form.max_export_workers" :min="1" :max="4" />
        </el-form-item>
      </div>

      <el-button
        type="primary"
        :loading="saving"
        @click="$emit('save', { ...form })"
      >
        保存并发设置
      </el-button>
    </el-form>
  </el-card>
</template>
