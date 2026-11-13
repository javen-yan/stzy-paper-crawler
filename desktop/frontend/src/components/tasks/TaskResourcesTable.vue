<script setup lang="ts">
import { computed } from 'vue'
import { FolderOpen } from 'lucide-vue-next'
import StatusTag from '../common/StatusTag.vue'
import type { TaskResource } from '../../types/tasks'

const RESOURCE_STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  failed: '失败',
  downloading: '处理中',
  pending: '待处理',
  partial: '部分完成',
  paid_unavailable: '付费跳过',
  preview_limited: '仅预览页',
  filtered: '条件过滤',
}

const props = defineProps<{
  resources: TaskResource[]
  localActions?: boolean
  statusFilter?: string
  statusCounts?: Record<string, number>
}>()
const emit = defineEmits<{ openLocation: [resource: TaskResource]; statusChange: [status: string] }>()

function resourceStatusLabel(status?: string) {
  if (!status) return '未知'
  return RESOURCE_STATUS_LABELS[status] || status
}

const totalCount = computed(() =>
  Object.values(props.statusCounts || {}).reduce((acc, n) => acc + Number(n || 0), 0),
)

const statusPills = computed(() =>
  Object.entries(props.statusCounts || {})
    .filter(([, count]) => Number(count) > 0)
    .map(([status, count]) => ({
      status,
      label: resourceStatusLabel(status),
      count: Number(count),
    })),
)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="resource-header">
        <div class="resource-filter-pills">
          <button
            type="button"
            class="res-pill"
            :class="{ active: !statusFilter }"
            @click="emit('statusChange', '')"
          >
            全部 ({{ totalCount || resources.length }})
          </button>
          <button
            v-for="pill in statusPills"
            :key="pill.status"
            type="button"
            class="res-pill"
            :class="{ active: statusFilter === pill.status }"
            @click="emit('statusChange', pill.status)"
          >
            {{ pill.label }} ({{ pill.count }})
          </button>
        </div>
      </div>
    </template>
    <el-table :data="resources" empty-text="暂无资源记录" row-key="id">
      <el-table-column label="试卷名称" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">{{ row.resource_name || row.name || row.title || row.resource_id || row.id || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <StatusTag :status="row.status || 'unknown'" :label="resourceStatusLabel(row.status)" />
        </template>
      </el-table-column>
      <el-table-column prop="subject" label="学科" width="90" />
      <el-table-column prop="grade" label="年级" width="90" />
      <el-table-column prop="province" label="地区" width="90" />
      <el-table-column prop="image_count" label="页数" width="80" />
      <el-table-column label="处理说明 / 原因" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="!row.error" class="reason-empty">-</span>
          <span v-else-if="row.status === 'completed'" class="reason-auto">
            {{ row.error }}
          </span>
          <span v-else class="reason-warn">
            {{ row.error }}
          </span>
        </template>
      </el-table-column>
      <el-table-column v-if="localActions" label="本地位置" width="100" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :icon="FolderOpen" :disabled="!row.local_dir" @click="$emit('openLocation', row)">
            打开
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.resource-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.resource-filter-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.res-pill {
  height: 28px;
  padding: 0 11px;
  border-radius: 999px;
  border: 1px solid var(--app-border);
  background: rgba(15, 23, 42, 0.6);
  color: var(--app-muted);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 140ms ease, background-color 140ms ease, color 140ms ease;
}

.res-pill:hover {
  border-color: rgba(129, 140, 248, 0.45);
  color: var(--app-text);
}

.res-pill.active {
  border-color: rgba(129, 140, 248, 0.72);
  background: rgba(99, 102, 241, 0.22);
  color: #ffffff;
  font-weight: 600;
}

.reason-empty {
  color: var(--app-muted);
}

.reason-auto {
  color: #6ee7b7;
  font-size: 12px;
}

.reason-warn {
  color: #fcd34d;
  font-size: 12px;
}
</style>
