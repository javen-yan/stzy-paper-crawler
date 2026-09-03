<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Archive, ArrowLeft, CirclePause, CirclePlay, Download, RotateCcw, XCircle } from 'lucide-vue-next'
import { openLocalPath } from '../api/local'
import { fetchCatalogs } from '../api/catalogs'
import FileTable from '../components/files/FileTable.vue'
import ExportZipPanel from '../components/files/ExportZipPanel.vue'
import EmptyState from '../components/common/EmptyState.vue'
import SimplePager from '../components/common/SimplePager.vue'
import TaskLogsPanel from '../components/tasks/TaskLogsPanel.vue'
import TaskProgress from '../components/tasks/TaskProgress.vue'
import TaskResourcesTable from '../components/tasks/TaskResourcesTable.vue'
import StatusTag from '../components/common/StatusTag.vue'
import { useExports } from '../composables/useExports'
import { useLayoutState } from '../composables/useLayoutState'
import { usePolling } from '../composables/usePolling'
import { useRuntime } from '../composables/useRuntime'
import { taskStatusLabel, useTasks } from '../composables/useTasks'
import { useToast } from '../composables/useToast'
import { resolveTaskFilters } from '../utils/filters'
import { taskDisplayName } from '../utils/taskDisplay'
import type { CatalogState } from '../types/catalogs'
import type { TaskDetailTabKey, TaskIssue, TaskOverviewStats } from '../types/tasks'

const props = defineProps<{ id: string }>()
const router = useRouter()
const toast = useToast()
const { setActiveTaskId } = useLayoutState()
const { selectedTask, logs, resources, selectTask, refreshSelectedTask, refreshLogs, refreshResources, createDownloadFromEstimate, runTaskAction } = useTasks()
const { currentExport, createTaskZip, refreshExport, exportDownloadUrl } = useExports()
const { canUseLocal } = useRuntime()
const activeTab = ref<TaskDetailTabKey>('overview')
const loading = ref(false)
const actionLoading = ref(false)
const zipLoading = ref(false)
const catalog = ref<CatalogState>({})
const selectedFilePaths = ref<string[]>([])
const resourcePage = ref(1)
const resourcePageSize = ref(50)
const resourceHasNextPage = ref(false)
const fileManagerKey = ref(0)
const resourceRefreshAt = ref(0)
const visibleResources = computed(() => resources.value.slice(0, resourcePageSize.value))

const polling = usePolling(async () => {
  await refreshSelectedTask()
  if (activeTab.value === 'logs') await refreshLogs()
  if (shouldRefreshResources()) await refreshResourcePage()
  if (currentTaskExport.value && !['completed', 'failed'].includes(currentTaskExport.value.status)) await refreshExport()
}, 2000, { hiddenIntervalMs: 15000 })

const overviewStats = computed<TaskOverviewStats>(() => {
  const stats = selectedTask.value?.stats || {}
  return {
    total: numberStat(stats.resources_total || stats.resources_seen),
    completed: numberStat(stats.resources_completed || stats.success),
    failed: numberStat(stats.failed),
    skipped: numberStat(stats.paid_skipped) + numberStat(stats.preview_limited) + numberStat(stats.filtered_skipped),
  }
})

const summaryMetrics = computed(() => {
  const stats = selectedTask.value?.stats || {}
  const processed = numberStat(stats.resources_completed || stats.success)
  const filtered = numberStat(stats.filtered_skipped)
  return [
    { label: '远端返回', value: numberStat(stats.resources_total || stats.resources_seen) },
    { label: '实际下载', value: Math.max(0, processed - filtered) },
    { label: '地区过滤', value: filtered },
    { label: '已下载图片', value: numberStat(stats.images_downloaded) },
    { label: '跳过付费', value: numberStat(stats.paid_skipped) },
    { label: '条件组合', value: `${numberStat(stats.completed_combos)}/${numberStat(stats.total_combos)}` },
  ]
})

const resolvedFilters = computed(() => resolveTaskFilters(selectedTask.value!, catalog.value))

const configSnapshot = computed(() => ({
  filters: selectedTask.value?.spec?.filters || {},
  subjects: selectedTask.value?.spec?.subjects || [],
  settings: selectedTask.value?.spec?.settings || {},
}))

const issues = computed<TaskIssue[]>(() => {
  const result: TaskIssue[] = []
  const task = selectedTask.value
  if (!task) return result
  if (task.error) {
    result.push({ type: 'task', title: '任务错误', detail: task.error, recovery: '查看日志定位原因，修复后可尝试恢复任务。' })
  }
  if (task.status === 'auth_expired') {
    result.push({ type: 'account', title: '账号登录失效', detail: '任务运行时检测到账号不可用。', recovery: '进入账号池验证或更新账号后，在本页点击恢复。' })
  }
  if (task.status === 'interrupted') {
    result.push({ type: 'task', title: '任务被中断', detail: '服务重启或异常退出导致任务停止。', recovery: '点击恢复，从检查点继续。' })
  }
  if (task.status === 'cancelled') {
    result.push({ type: 'task', title: '任务已取消', detail: '任务已停止调度，未完成的范围会保留。', recovery: '点击恢复，从检查点继续下载未完成部分。' })
  }
  for (const resource of visibleResources.value) {
    if (resource.error) {
      result.push({
        type: 'resource',
        title: String(resource.resource_name || resource.name || resource.resource_id || '资源失败'),
        detail: String(resource.error),
        recovery: '系统恢复任务时会继续扫描未完成范围；也可以重新提交任务。',
      })
    }
  }
  if (!result.length) {
    result.push({ type: 'task', title: '暂无需处理问题', detail: '当前任务没有记录到阻塞性错误。', recovery: '可以继续等待任务完成，或在文件结果中查看已发布文件。' })
  }
  return result
})

const currentTaskExport = computed(() => (currentExport.value?.task_id === props.id ? currentExport.value : null))
const exportDownload = computed(() => (currentTaskExport.value ? exportDownloadUrl(currentTaskExport.value.id) : ''))
const canResume = computed(() => ['paused', 'partial_completed', 'failed', 'auth_expired', 'interrupted', 'cancelled'].includes(selectedTask.value?.status || ''))
const canPause = computed(() => ['running', 'queued'].includes(selectedTask.value?.status || ''))
const canStartDownload = computed(() => selectedTask.value?.mode === 'estimate' && selectedTask.value.status === 'completed')
const isTaskActive = computed(() => ['queued', 'running', 'pausing'].includes(selectedTask.value?.status || ''))
const canCreateZip = computed(() => Boolean(selectedFilePaths.value.length || ['completed', 'partial_completed'].includes(selectedTask.value?.status || '')))

function numberStat(value: unknown) {
  const numeric = Number(value || 0)
  return Number.isFinite(numeric) ? numeric : 0
}

async function refreshAll() {
  await selectTask(props.id, { includeLogs: false, includeResources: false })
  await refreshResourcePage()
}

async function refreshResourcePage() {
  const payload = await refreshResources({ limit: resourcePageSize.value + 1, offset: (resourcePage.value - 1) * resourcePageSize.value })
  resourceHasNextPage.value = Boolean(payload && payload.items.length > resourcePageSize.value)
  resourceRefreshAt.value = Date.now()
}

function shouldRefreshResources() {
  if (!['resources', 'issues'].includes(activeTab.value)) return false
  return Date.now() - resourceRefreshAt.value > (isTaskActive.value ? 3000 : 15000)
}

function refreshFileManager() {
  selectedFilePaths.value = []
  fileManagerKey.value += 1
}

async function changeResourcePageSize(value: number) {
  resourcePageSize.value = value
  resourcePage.value = 1
  await refreshResourcePage()
}

async function prevResourcePage() {
  if (resourcePage.value <= 1) return
  resourcePage.value -= 1
  await refreshResourcePage()
}

async function nextResourcePage() {
  if (!resourceHasNextPage.value) return
  resourcePage.value += 1
  await refreshResourcePage()
}

async function handleAction(action: 'pause' | 'resume' | 'cancel' | 'archive') {
  if (!selectedTask.value) return
  if (['cancel', 'archive'].includes(action)) {
    await ElMessageBox.confirm(action === 'cancel' ? '取消后任务会停止调度，在途操作会收尾。' : '归档只隐藏任务，不删除文件。', '确认操作', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
  }
  actionLoading.value = true
  try {
    await runTaskAction(selectedTask.value.id, action)
    toast.success('操作已提交')
  } catch (error) {
    toast.error(error)
  } finally {
    actionLoading.value = false
  }
}

async function startDownloadFromEstimate() {
  if (!selectedTask.value) return
  await ElMessageBox.confirm('沿用本次预估的筛选条件创建下载任务。', '开始下载', {
    confirmButtonText: '开始下载',
    cancelButtonText: '取消',
    type: 'info',
  })
  actionLoading.value = true
  try {
    const task = await createDownloadFromEstimate(selectedTask.value)
    setActiveTaskId(task.id)
    toast.success('下载任务已创建')
    router.push(`/tasks/${task.id}`)
  } catch (error) {
    toast.error(error, '下载任务创建失败')
  } finally {
    actionLoading.value = false
  }
}

async function createZip() {
  zipLoading.value = true
  try {
    await createTaskZip(
      props.id,
      selectedFilePaths.value,
    )
    toast.success('ZIP 任务已提交')
  } catch (error) {
    toast.error(error, 'ZIP 生成失败')
  } finally {
    zipLoading.value = false
  }
}

async function openResourceDir(resource: { local_dir?: string }) {
  if (!resource.local_dir) return
  try {
    await openLocalPath(resource.local_dir)
  } catch (error) {
    toast.error(error, '打开资源目录失败')
  }
}

onMounted(async () => {
  loading.value = true
  setActiveTaskId(props.id)
  try {
    await refreshAll()
    fetchCatalogs().then((data) => (catalog.value = data)).catch(() => {})
    polling.start()
  } catch (error) {
    toast.error(error, '任务详情加载失败')
  } finally {
    loading.value = false
  }
})

watch(
  () => activeTab.value,
  async (tab) => {
    if (tab === 'logs') await refreshLogs()
    if (tab === 'resources' || tab === 'issues') await refreshResourcePage()
  },
)
</script>

<template>
  <div class="page-stack">
    <el-skeleton v-if="loading" :rows="8" animated />

    <template v-else-if="selectedTask">
      <el-card shadow="never" class="task-detail-header-card">
        <div class="detail-header">
          <div class="detail-header-left">
            <el-button :icon="ArrowLeft" text @click="router.push('/tasks')">返回</el-button>
            <div class="detail-title">
              <h2>{{ taskDisplayName(selectedTask) }}</h2>
              <small class="mono">{{ selectedTask.id }}</small>
            </div>
            <StatusTag :status="selectedTask.status" :label="taskStatusLabel(selectedTask)" />
          </div>
          <div class="detail-header-actions">
            <el-button v-if="canStartDownload" :icon="Download" type="primary" :loading="actionLoading" @click="startDownloadFromEstimate">开始下载</el-button>
            <el-button :icon="CirclePause" :disabled="!canPause" :loading="actionLoading" @click="handleAction('pause')">暂停</el-button>
            <el-button :icon="CirclePlay" :disabled="!canResume" :loading="actionLoading" @click="handleAction('resume')">恢复</el-button>
            <el-button :icon="XCircle" type="danger" plain :loading="actionLoading" @click="handleAction('cancel')">取消</el-button>
            <el-button :icon="Archive" :loading="actionLoading" @click="handleAction('archive')">归档</el-button>
            <el-button :icon="Download" type="primary" plain :loading="zipLoading" :disabled="!canCreateZip" @click="createZip">下载 ZIP</el-button>
          </div>
        </div>
      </el-card>

      <section class="detail-desc">
        <el-card shadow="never">
          <template #header>进度</template>
          <TaskProgress :task="selectedTask" />
          <div class="summary-grid detail-stats-row">
            <div class="detail-stat" data-tone="idle">
              <span class="detail-stat-label">远端返回</span>
              <strong>{{ overviewStats.total }}</strong>
            </div>
            <div class="detail-stat" data-tone="success">
              <span class="detail-stat-label">已完成</span>
              <strong>{{ overviewStats.completed }}</strong>
            </div>
            <div class="detail-stat" data-tone="danger">
              <span class="detail-stat-label">失败</span>
              <strong>{{ overviewStats.failed }}</strong>
            </div>
            <div class="detail-stat" data-tone="warning">
              <span class="detail-stat-label">跳过/受限</span>
              <strong>{{ overviewStats.skipped }}</strong>
            </div>
          </div>
        </el-card>

        <el-card shadow="never">
          <template #header>任务信息</template>
          <el-descriptions :column="1" border class="task-meta">
            <el-descriptions-item label="模式">{{ selectedTask.mode === 'estimate' ? '预估' : '采集下载' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ selectedTask.created_at }}</el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ selectedTask.updated_at }}</el-descriptions-item>
            <el-descriptions-item label="开始时间">{{ selectedTask.started_at || '未记录' }}</el-descriptions-item>
            <el-descriptions-item label="结束时间">{{ selectedTask.ended_at || '未结束' }}</el-descriptions-item>
            <el-descriptions-item label="当前代理">{{ selectedTask.active_proxy || '未使用代理' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </section>
      <el-alert v-if="selectedTask.error" :title="selectedTask.error" type="error" show-icon :closable="false" />

      <el-tabs v-model="activeTab" class="detail-tabs">
        <el-tab-pane label="概览" name="overview">
          <el-card shadow="never">
            <template #header>运行概览</template>
            <el-descriptions :column="2" border>
              <el-descriptions-item v-for="metric in summaryMetrics" :key="metric.label" :label="metric.label">
                {{ metric.value }}
              </el-descriptions-item>
              <el-descriptions-item label="异常数量">{{ overviewStats.failed + overviewStats.skipped }}</el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="运行日志" name="logs">
          <TaskLogsPanel :logs="logs" @refresh="refreshLogs" />
        </el-tab-pane>

        <el-tab-pane label="筛选配置" name="config">
          <div class="content-grid">
            <el-card shadow="never">
              <template #header>筛选条件</template>
              <el-descriptions :column="1" border>
                <el-descriptions-item v-for="row in resolvedFilters" :key="row.key" :label="row.label">
                  {{ row.value }}
                </el-descriptions-item>
                <el-descriptions-item v-if="!resolvedFilters.length" label="筛选条件">未记录</el-descriptions-item>
              </el-descriptions>
            </el-card>
            <el-card shadow="never">
              <template #header>学科与策略</template>
              <el-table :data="configSnapshot.subjects" empty-text="未记录学科信息">
                <el-table-column label="学科名称" prop="name" min-width="160" />
              </el-table>
            </el-card>
          </div>
        </el-tab-pane>

        <el-tab-pane label="资源列表" name="resources">
          <TaskResourcesTable :resources="visibleResources" :local-actions="canUseLocal" @open-location="openResourceDir" />
          <SimplePager
            class="list-pager"
            :page="resourcePage"
            :page-size="resourcePageSize"
            :item-count="visibleResources.length"
            :has-next="resourceHasNextPage"
            label="资源"
            @prev="prevResourcePage"
            @next="nextResourcePage"
            @refresh="refreshResourcePage"
            @page-size-change="changeResourcePageSize"
          />
        </el-tab-pane>

        <el-tab-pane label="文件结果" name="files">
          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>任务文件列表</span>
                <small class="block-muted">按实际保存层级展示：学科 / 年级 / 学期 / 地区 / 场景。</small>
                <el-button :icon="RotateCcw" @click="refreshFileManager">刷新文件</el-button>
              </div>
            </template>
            <FileTable
              :key="fileManagerKey"
              :task-id="props.id"
              @selection-change="selectedFilePaths = $event"
            />
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="导出记录" name="exports">
          <ExportZipPanel :export-job="currentTaskExport" :download-url="exportDownload" :disabled="!canCreateZip" :loading="zipLoading" @create="createZip" />
          <el-alert
            v-if="!currentTaskExport"
            title="暂无导出记录"
            type="info"
            show-icon
            :closable="false"
          />
        </el-tab-pane>

        <el-tab-pane label="错误与恢复" name="issues">
          <el-card shadow="never">
            <template #header>问题诊断</template>
            <el-timeline>
              <el-timeline-item v-for="issue in issues" :key="`${issue.type}-${issue.title}-${issue.detail}`" :type="issue.title === '暂无需处理问题' ? 'success' : 'warning'">
                <strong>{{ issue.title }}</strong>
                <p>{{ issue.detail }}</p>
                <small>{{ issue.recovery }}</small>
              </el-timeline-item>
            </el-timeline>
            <el-button v-if="canResume" type="primary" :icon="CirclePlay" :loading="actionLoading" @click="handleAction('resume')">恢复任务</el-button>
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </template>

    <EmptyState v-else title="没有找到任务" description="任务可能已被删除。" action-text="返回任务中心" @action="router.push('/tasks')" />
  </div>
</template>

<style scoped>
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.detail-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.detail-title {
  min-width: 0;
}

.detail-title h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-title small {
  display: block;
  font-family: var(--app-mono);
  color: var(--app-faint);
  font-size: 11px;
}

.detail-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.detail-desc {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.detail-stats-row .summary-grid,
.detail-stats-row {
  margin-top: 16px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.detail-stat {
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-bg-2);
  padding: 14px 16px;
  display: grid;
  gap: 6px;
}

.detail-stat-label {
  color: var(--app-muted);
  font-size: 13px;
  font-family: var(--app-mono);
}

.detail-stat strong {
  font-size: 28px;
  line-height: 1.1;
  font-family: var(--app-mono);
  color: var(--app-text);
}

.detail-stat[data-tone="success"] strong {
  color: var(--app-accent);
  text-shadow: 0 0 16px rgba(152, 195, 121, 0.4);
}

.detail-stat[data-tone="danger"] strong {
  color: var(--app-danger);
  text-shadow: 0 0 16px rgba(224, 108, 117, 0.4);
}

.detail-stat[data-tone="warning"] strong {
  color: var(--app-warning);
  text-shadow: 0 0 16px rgba(229, 192, 123, 0.4);
}

.task-meta {
  margin-top: 0;
}

@media (max-width: 1024px) {
  .detail-desc {
    grid-template-columns: 1fr;
  }

  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
