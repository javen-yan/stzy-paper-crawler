<script setup lang="ts">
import { FolderOpen, Package } from 'lucide-vue-next'
import { openLocalPath } from '../../api/local'
import { useToast } from '../../composables/useToast'
import type { ExportJob } from '../../types/exports'

const props = defineProps<{ exportJob: ExportJob | null; disabled?: boolean; loading?: boolean }>()
defineEmits<{ create: [] }>()

const toast = useToast()

async function revealZip() {
  const filePath = props.exportJob?.file_path
  if (!filePath) return
  try {
    await openLocalPath(filePath, { reveal: true })
  } catch (err) {
    toast.error(err, '打开所在位置失败')
  }
}
</script>

<template>
  <el-card shadow="never" class="zip-panel">
    <template #header>
      <div class="card-header">
        <span>批量导出 ZIP</span>
        <el-button type="primary" :icon="Package" :disabled="disabled" :loading="loading" @click="$emit('create')">另存为 ZIP</el-button>
      </div>
    </template>
    <el-alert
      title="弹出系统原生保存对话框，将当前任务的全部或勾选文件直接打包保存为本地 ZIP 压缩包。"
      type="info"
      :closable="false"
      show-icon
    />
    <div v-if="exportJob" class="zip-status">
      <el-tag :type="exportJob.status === 'completed' ? 'success' : exportJob.status === 'failed' ? 'danger' : 'warning'">
        {{ exportJob.status === 'completed' ? '已保存' : exportJob.status }}
      </el-tag>
      <span>{{ exportJob.file_path || exportJob.display_name || exportJob.id }}</span>
      <el-button v-if="exportJob.status === 'completed' && exportJob.file_path" :icon="FolderOpen" @click="revealZip">在文件管理器中显示</el-button>
      <el-alert v-if="exportJob.status === 'failed'" :title="exportJob.error || 'ZIP 生成失败'" type="error" show-icon :closable="false" />
    </div>
  </el-card>
</template>
