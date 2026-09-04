<script setup lang="ts">
import { computed } from 'vue'
import { FolderOpen } from 'lucide-vue-next'
import StatusTag from '../common/StatusTag.vue'
import type { TaskResource } from '../../types/tasks'

const props = defineProps<{
  resources: TaskResource[]
  localActions?: boolean
  statusFilter?: string
  statusCounts?: Record<string, number>
}>()
const emit = defineEmits<{ openLocation: [resource: TaskResource]; statusChange: [status: string] }>()
const statusOptions = computed(() => Object.entries(props.statusCounts || {}).filter(([, count]) => Number(count) > 0))
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span>资源记录</span>
        <el-select :model-value="statusFilter" clearable placeholder="按状态筛选" class="resource-filter" @change="emit('statusChange', String($event || ''))">
          <el-option v-for="[status, count] in statusOptions" :key="status" :label="`${status} (${count})`" :value="status" />
        </el-select>
      </div>
    </template>
    <el-table :data="resources" empty-text="暂无资源记录" row-key="id">
      <el-table-column label="资源" min-width="220">
        <template #default="{ row }">{{ row.resource_name || row.name || row.title || row.resource_id || row.id || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }"><StatusTag :status="row.status || 'unknown'" :label="row.status || '未知'" /></template>
      </el-table-column>
      <el-table-column prop="subject" label="学科" width="100" />
      <el-table-column prop="grade" label="年级" width="100" />
      <el-table-column prop="province" label="地区" width="100" />
      <el-table-column prop="image_count" label="文件数" width="90" />
      <el-table-column prop="error" label="失败原因" min-width="220" show-overflow-tooltip />
      <el-table-column v-if="localActions" label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button :icon="FolderOpen" :disabled="!row.local_dir" @click="$emit('openLocation', row)">打开</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>
