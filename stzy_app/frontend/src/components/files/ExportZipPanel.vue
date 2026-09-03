<script setup lang="ts">
import { Download, Package } from 'lucide-vue-next'
import type { ExportJob } from '../../types/exports'

defineProps<{ exportJob: ExportJob | null; downloadUrl?: string; disabled?: boolean; loading?: boolean }>()
defineEmits<{ create: [] }>()
</script>

<template>
  <el-card shadow="never" class="zip-panel">
    <template #header>
      <div class="card-header">
        <span>批量 ZIP</span>
        <el-button type="primary" :icon="Package" :disabled="disabled" :loading="loading" @click="$emit('create')">生成 ZIP</el-button>
      </div>
    </template>
    <el-alert
      title="后台打包当前任务的已发布文件。"
      type="info"
      :closable="false"
      show-icon
    />
    <div v-if="exportJob" class="zip-status">
      <el-tag :type="exportJob.status === 'completed' ? 'success' : exportJob.status === 'failed' ? 'danger' : 'warning'">
        {{ exportJob.status }}
      </el-tag>
      <span>{{ exportJob.display_name || exportJob.id }}</span>
      <el-button v-if="exportJob.status === 'completed' && downloadUrl" :icon="Download" tag="a" :href="downloadUrl">下载 ZIP</el-button>
      <el-alert v-if="exportJob.status === 'failed'" :title="exportJob.error || 'ZIP 生成失败'" type="error" show-icon :closable="false" />
    </div>
  </el-card>
</template>
