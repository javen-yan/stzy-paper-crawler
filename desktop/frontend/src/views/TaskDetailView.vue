<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Archive, ArrowLeft, CirclePause, CirclePlay, Download, FolderOpen, RotateCcw, XCircle } from 'lucide-vue-next'
import { openLocalPath } from '../api/local'
import { fetchCatalogs } from '../api/catalogs'
import { fetchTaskResources } from '../api/tasks'
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
import type { TaskDetailTabKey, TaskIssue, TaskOverviewStats, TaskResource } from '../types/tasks'

const props = defineProps<{ id: string }>()
const router = useRouter()
const toast = useToast()
const { setActiveTaskId } = useLayoutState()
const {
  selectedTask,
  logs,
  resources,
  selectTask,
  refreshSelectedTask,
  refreshLogs,
  refreshResources,
  createDownloadFromEstimate,
  runTaskAction,
} = useTasks()
const { currentExport, createTaskZip } = useExports()
const { canUseLocal } = useRuntime()
const activeTab = ref<TaskDetailTabKey>('files')
const loading = ref(false)
const actionLoading = ref(false)
const zipLoading = ref(false)
const catalog = ref<CatalogState>({})
const selectedFilePaths = ref<string[]>([])
const resourcePage = ref(1)
const resourcePageSize = ref(50)
const resourceHasNextPage = ref(false)
const resourceTotal = ref(0)
const resourceStatusCounts = ref<Record<string, number>>({})
const resourceStatusFilter = ref('')
const fileManagerKey = ref(0)
const resourceRefreshAt = ref(0)
const issueResources = ref<TaskResource[]>([])
const issueRefreshAt = ref(0)
const visibleResources = computed(() => resources.value.slice(0, resourcePageSize.value))

const polling = usePolling(
  async () => {
    await refreshSelectedTask()
    if (activeTab.value === 'logs') await refreshLogs()
    if (shouldRefreshResources()) await refreshResourcePage()
    if (shouldRefreshIssues()) await refreshIssueResources()
  },
  3000,
  { hiddenIntervalMs: 15000 },
)

const overviewStats = computed<TaskOverviewStats>(() => {
  const stats = selectedTask.value?.stats || {}
  const total = numberStat(stats.resources_total || stats.resources_seen)
  const processed = numberStat(stats.resources_processed || stats.resources_completed || stats.success)
  const skipped = numberStat(stats.paid_skipped) + numberStat(stats.preview_limited) + numberStat(stats.filtered_skipped)
  return {
    total,
    processed,
    completed: numberStat(stats.resources_success || stats.resources_completed || stats.success),
    failed: numberStat(stats.failed),
    pending: Math.max(0, total - processed),
    skipped,
  }
})

const resolvedFilters = computed(() => (selectedTask.value ? resolveTaskFilters(selectedTask.value, catalog.value) : []))

const subjectTagNames = computed(() => {
  const subjects = selectedTask.value?.spec?.subjects || []
  const names = subjects.map((s) => s.name || s.code || '').filter(Boolean)
  return names.length ? names.join('、') : '全部学科'
})

const taskError = computed(() => {
  const task = selectedTask.value
  if (!task?.error) return ''
  return ['failed', 'auth_expired', 'interrupted'].includes(task.status || '') ? task.error : ''
})

const issues = computed<TaskIssue[]>(() => {
  const result: TaskIssue[] = []
  const task = selectedTask.value
  if (!task) return result
  if (taskError.value) {
    result.push({
      type: 'task',
      title: '任务异常停止',
      detail: taskError.value,
      recovery: '检查网络或账号状态后，点击「继续任务」从断点恢复。',
    })
  }
  if (task.status === 'auth_expired') {
    result.push({
      type: 'account',
      title: '账号登录已失效',
      detail: '任务执行过程中检测到当前账号不可用。',
      recovery: '前往「账号管理」重新验证或补充可用账号后恢复任务。',
    })
  }
  if (task.status === 'interrupted') {
    result.push({
      type: 'task',
      title: '任务中断',
      detail: '客户端退出或重启导致未完成任务暂停。',
      recovery: '点击「继续任务」即可跳过已完成资源继续下载。',
    })
  }
  for (const resource of issueResources.value) {
    const detail = issueResourceDetail(resource)
    result.push({
      type: 'resource',
      title: String(resource.resource_name || resource.name || resource.resource_id || '资源异常'),
      detail,
      recovery: issueResourceRecovery(resource, detail),
      local_dir: resource.local_dir || undefined,
    })
  }
  return result
})

const currentTaskExport = computed(() => (currentExport.value?.task_id === props.id ? currentExport.value : null))
const canResume = computed(() =>
  selectedTask.value?.mode !== 'estimate' &&
  ['paused', 'partial_completed', 'failed', 'auth_expired', 'interrupted', 'cancelled'].includes(
    selectedTask.value?.status || '',
  ),
)
const canPause = computed(() => ['running', 'queued'].includes(selectedTask.value?.status || ''))
const canStartDownload = computed(() => selectedTask.value?.mode === 'estimate' && selectedTask.value.status === 'completed')
const isTaskActive = computed(() => ['queued', 'running', 'pausing'].includes(selectedTask.value?.status || ''))
const hasLocalFiles = computed(() =>
  Boolean(
    selectedTask.value?.mode !== 'estimate' &&
      (overviewStats.value.completed > 0 || ['completed', 'partial_completed'].includes(selectedTask.value?.status || '')),
  ),
)
const canCreateZip = computed(() => Boolean(selectedFilePaths.value.length || hasLocalFiles.value))

function numberStat(value: unknown) {
  const numeric = Number(value || 0)
  return Number.isFinite(numeric) ? numeric : 0
}

function formatTime(raw?: string) {
  if (!raw) return '-'
  return raw.replace('T', ' ').replace(/\.\d+/, '').replace(/([+-]\d{2}:\d{2}|Z)$/, '')
}

async function refreshAll() {
  await selectTask(props.id, { includeLogs: false, includeResources: false })
  const status = selectedTask.value?.status || ''
  if (selectedTask.value?.mode === 'estimate') {
    activeTab.value = 'logs'
    await refreshLogs(true)
  } else if (['failed', 'auth_expired', 'interrupted'].includes(status)) {
    activeTab.value = 'issues'
    await refreshIssueResources()
  } else if (['running', 'queued'].includes(status) && overviewStats.value.completed === 0) {
    activeTab.value = 'resources'
    await refreshResourcePage()
  } else {
    activeTab.value = 'files'
    await refreshResourcePage()
  }
}

async function refreshResourcePage() {
  const payload = await refreshResources({
    limit: resourcePageSize.value + 1,
    offset: (resourcePage.value - 1) * resourcePageSize.value,
    status: resourceStatusFilter.value,
  })
  resourceHasNextPage.value = Boolean(payload && payload.items.length > resourcePageSize.value)
  resourceTotal.value = Number(payload?.total || 0)
  resourceStatusCounts.value = payload?.status_counts || {}
  resourceRefreshAt.value = Date.now()
}

async function refreshIssueResources() {
  const statuses = ['failed', 'paid_unavailable', 'partial']
  const payloads = await Promise.all(statuses.map((status) => fetchTaskResources(props.id, 30, 0, status)))
  const seen = new Set<string>()
  issueResources.value = payloads
    .flatMap((payload) => payload.items)
    .filter((resource) => {
      const key = String(resource.resource_id || resource.id || resource.resource_name || '')
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    })
    .slice(0, 80)
  issueRefreshAt.value = Date.now()
}

function shouldRefreshResources() {
  if (activeTab.value !== 'resources') return false
  return Date.now() - resourceRefreshAt.value > (isTaskActive.value ? 3000 : 15000)
}

function shouldRefreshIssues() {
  if (activeTab.value !== 'issues') return false
  return Date.now() - issueRefreshAt.value > (isTaskActive.value ? 3000 : 15000)
}

function issueResourceDetail(resource: TaskResource) {
  if (resource.error) return String(resource.error)
  const status = String(resource.status || '')
  if (status === 'paid_unavailable') return '当前账号池无可用 VIP 额度下载该资源。'
  if (status === 'partial') return '仅完成部分页面，继续任务时会补齐。'
  return '资源未完成。'
}

function issueResourceRecovery(resource: TaskResource, detail: string) {
  const status = String(resource.status || '')
  if (status === 'paid_unavailable') {
    return '前往「账号管理」补充可用 VIP 账号后，点击「继续任务」即可补齐。'
  }
  if (detail.includes('RAR') || detail.includes('7z') || detail.includes('密码') || detail.includes('音频')) {
    return '系统已将原文件完整保存在本地目录，可直接点击「打开原文件目录」查看使用。'
  }
  if (detail.includes('LibreOffice')) {
    return '安装 LibreOffice 后点击「继续任务」，即可将已保存的原文件自动转换为 PDF。'
  }
  if (resource.local_dir && (detail.includes('已保留') || detail.includes('已保存'))) {
    return '原文件已保存在本地目录，可直接打开查看；也可稍后继续任务重试转换。'
  }
  return '恢复任务时仅重试未完成资源，不会重复下载已保存文件。'
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

async function changeResourceStatusFilter(status: string) {
  resourceStatusFilter.value = status
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
    try {
      await ElMessageBox.confirm(
        action === 'cancel' ? '取消后任务停止下载，已完成文件保留。' : '归档后任务从默认列表中隐藏，本地文件不会删除。',
        action === 'cancel' ? '取消任务' : '归档任务',
        {
          confirmButtonText: '确认',
          cancelButtonText: '返回',
          type: 'warning',
        },
      )
    } catch {
      return
    }
  }
  actionLoading.value = true
  try {
    await runTaskAction(selectedTask.value.id, action)
    toast.success(action === 'archive' ? '任务已归档' : '操作已执行')
    if (action === 'archive') {
      router.push('/tasks')
    }
  } catch (error) {
    toast.error(error)
  } finally {
    actionLoading.value = false
  }
}

async function startDownloadFromEstimate() {
  if (!selectedTask.value) return
  actionLoading.value = true
  try {
    const task = await createDownloadFromEstimate(selectedTask.value)
    setActiveTaskId(task.id)
    toast.success('已创建下载任务')
    router.push(`/tasks/${task.id}`)
  } catch (error) {
    toast.error(error, '创建下载任务失败')
  } finally {
    actionLoading.value = false
  }
}

async function createZip() {
  zipLoading.value = true
  try {
    const baseLabel = selectedTask.value ? taskDisplayName(selectedTask.value).replace(/[\\/:*?"<>|]+/g, '_') : props.id
    const job = await createTaskZip(props.id, selectedFilePaths.value, `${baseLabel}.zip`)
    if (job) {
      toast.success(`ZIP 已导出至 ${job.file_path || job.display_name || ''}`)
    }
  } catch (error) {
    toast.error(error, '导出 ZIP 失败')
  } finally {
    zipLoading.value = false
  }
}

async function openTaskFolder() {
  try {
    await openLocalPath('', { taskId: props.id })
  } catch (error) {
    toast.error(error, '打开本地目录失败')
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
    fetchCatalogs()
      .then((data) => (catalog.value = data))
      .catch(() => {})
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
    if (tab === 'logs') await refreshLogs(true)
    if (tab === 'resources') await refreshResourcePage()
    if (tab === 'issues') await refreshIssueResources()
  },
)
</script>

<template>
  <div class="page-stack">
    <el-skeleton v-if="loading" :rows="8" animated />

    <template v-else-if="selectedTask">
      <!-- 顶部标题与操作栏 -->
      <el-card shadow="never" class="task-detail-header-card">
        <div class="detail-header">
          <div class="detail-header-left">
            <el-button :icon="ArrowLeft" text @click="router.push('/tasks')">返回</el-button>
            <div class="detail-title">
              <div class="title-row">
                <h2>{{ taskDisplayName(selectedTask) }}</h2>
                <StatusTag :status="selectedTask.status" :label="taskStatusLabel(selectedTask)" />
              </div>
              <small class="meta-subline">
                创建于 {{ formatTime(selectedTask.created_at) }}
                <template v-if="selectedTask.active_proxy"> · 代理 {{ selectedTask.active_proxy }}</template>
              </small>
            </div>
          </div>

          <div class="detail-header-actions">
            <el-button v-if="canStartDownload" :icon="Download" type="primary" :loading="actionLoading" @click="startDownloadFromEstimate">
              开始下载
            </el-button>
            <el-button v-if="hasLocalFiles" :icon="FolderOpen" @click="openTaskFolder">打开文件夹</el-button>
            <el-button v-if="selectedTask.mode !== 'estimate'" :icon="Download" :loading="zipLoading" :disabled="!canCreateZip" @click="createZip">
              {{ selectedFilePaths.length ? `导出已选 (${selectedFilePaths.length})` : '导出 ZIP' }}
            </el-button>
            <el-button v-if="canPause" :icon="CirclePause" :loading="actionLoading" @click="handleAction('pause')">暂停</el-button>
            <el-button v-if="canResume" :icon="CirclePlay" type="primary" :loading="actionLoading" @click="handleAction('resume')">继续任务</el-button>
            <el-button v-if="isTaskActive" :icon="XCircle" type="danger" plain :loading="actionLoading" @click="handleAction('cancel')">取消</el-button>
            <el-button v-if="!selectedTask.archived" :icon="Archive" :loading="actionLoading" @click="handleAction('archive')">归档</el-button>
          </div>
        </div>
      </el-card>

      <!-- 核心进度与筛选摘要 -->
      <section class="detail-overview-grid">
        <el-card shadow="never">
          <TaskProgress :task="selectedTask" />
          <div class="detail-stats-row">
            <div class="detail-stat" data-tone="idle">
              <span class="detail-stat-label">匹配总数</span>
              <strong>{{ overviewStats.total }}</strong>
            </div>
            <div class="detail-stat" data-tone="success">
              <span class="detail-stat-label">已完成</span>
              <strong>{{ overviewStats.completed }}</strong>
            </div>
            <div class="detail-stat" data-tone="idle">
              <span class="detail-stat-label">待处理</span>
              <strong>{{ overviewStats.pending }}</strong>
            </div>
            <div class="detail-stat" data-tone="danger">
              <span class="detail-stat-label">失败</span>
              <strong>{{ overviewStats.failed }}</strong>
            </div>
            <div class="detail-stat" data-tone="warning">
              <span class="detail-stat-label">跳过 / 过滤</span>
              <strong>{{ overviewStats.skipped }}</strong>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="filter-snapshot-card">
          <div class="snapshot-title">筛选范围</div>
          <div class="snapshot-kv-list">
            <div class="snapshot-kv">
              <span>学科</span>
              <strong>{{ subjectTagNames }}</strong>
            </div>
            <div v-for="row in resolvedFilters" :key="row.key" class="snapshot-kv">
              <span>{{ row.label }}</span>
              <strong>{{ row.value }}</strong>
            </div>
            <div class="snapshot-kv">
              <span>已下载页数</span>
              <strong class="mono">{{ numberStat(selectedTask.stats?.images_downloaded) }}</strong>
            </div>
          </div>
        </el-card>
      </section>

      <el-alert v-if="taskError" :title="taskError" type="error" show-icon :closable="false" />

      <ExportZipPanel
        v-if="currentTaskExport"
        :export-job="currentTaskExport"
        :disabled="!canCreateZip"
        :loading="zipLoading"
        @create="createZip"
      />

      <!-- 精简后的 4 个功能页签 -->
      <el-tabs v-model="activeTab" class="detail-tabs">
        <el-tab-pane v-if="selectedTask.mode !== 'estimate'" label="本地文件" name="files">
          <el-card shadow="never">
            <template #header>
              <div class="card-header files-card-header">
                <span>已保存文件（点击文件名可直接预览）</span>
                <div class="files-card-actions">
                  <el-button size="small" :icon="RotateCcw" @click="refreshFileManager">刷新目录</el-button>
                </div>
              </div>
            </template>
            <FileTable
              :key="fileManagerKey"
              :task-id="props.id"
              @selection-change="selectedFilePaths = $event"
            />
          </el-card>
        </el-tab-pane>

        <el-tab-pane v-if="selectedTask.mode !== 'estimate'" :label="`资源明细 (${resourceTotal || overviewStats.total})`" name="resources">
          <TaskResourcesTable
            :resources="visibleResources"
            :local-actions="canUseLocal"
            :status-filter="resourceStatusFilter"
            :status-counts="resourceStatusCounts"
            @open-location="openResourceDir"
            @status-change="changeResourceStatusFilter"
          />
          <SimplePager
            class="list-pager"
            :page="resourcePage"
            :page-size="resourcePageSize"
            :item-count="visibleResources.length"
            :has-next="resourceHasNextPage"
            :label="`共 ${resourceTotal} 条资源`"
            @prev="prevResourcePage"
            @next="nextResourcePage"
            @refresh="refreshResourcePage"
            @page-size-change="changeResourcePageSize"
          />
        </el-tab-pane>

        <el-tab-pane
          v-if="selectedTask.mode !== 'estimate'"
          :label="overviewStats.failed > 0 ? `问题诊断 (${overviewStats.failed})` : '问题诊断'"
          name="issues"
        >
          <el-card shadow="never">
            <template v-if="issues.length">
              <el-timeline>
                <el-timeline-item
                  v-for="issue in issues"
                  :key="`${issue.type}-${issue.title}-${issue.detail}`"
                  type="warning"
                >
                  <div class="issue-row-head">
                    <strong>{{ issue.title }}</strong>
                    <el-button
                      v-if="canUseLocal && issue.local_dir"
                      size="small"
                      :icon="FolderOpen"
                      @click="openResourceDir({ local_dir: issue.local_dir })"
                    >
                      打开原文件目录
                    </el-button>
                  </div>
                  <p>{{ issue.detail }}</p>
                  <small>{{ issue.recovery }}</small>
                </el-timeline-item>
              </el-timeline>
              <el-button v-if="canResume" type="primary" :icon="CirclePlay" :loading="actionLoading" @click="handleAction('resume')">
                重试未完成资源
              </el-button>
            </template>
            <EmptyState
              v-else
              title="当前没有异常记录"
              description="所有已扫描资源状态正常。"
            />
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="运行日志" name="logs">
          <TaskLogsPanel :logs="logs" @refresh="refreshLogs(true)" />
        </el-tab-pane>
      </el-tabs>
    </template>

    <EmptyState v-else title="未找到该任务" description="该任务可能已被删除。" action-text="返回任务列表" @action="router.push('/tasks')" />
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
  gap: 10px;
  min-width: 0;
}

.detail-title {
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.detail-title h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-subline {
  display: block;
  margin-top: 3px;
  color: var(--app-muted);
  font-size: 12px;
}

.detail-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.detail-overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.9fr);
  gap: 16px;
  align-items: stretch;
}

.detail-stats-row {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.detail-stat {
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: rgba(14, 20, 34, 0.72);
  padding: 11px 12px;
  display: grid;
  gap: 4px;
}

.detail-stat-label {
  color: var(--app-muted);
  font-size: 12px;
}

.detail-stat strong {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  color: var(--app-text);
}

.detail-stat[data-tone="success"] strong {
  color: var(--app-accent);
}

.detail-stat[data-tone="danger"] strong {
  color: var(--app-danger);
}

.detail-stat[data-tone="warning"] strong {
  color: var(--app-warning);
}

.filter-snapshot-card :deep(.el-card__body) {
  display: grid;
  gap: 10px;
  align-content: start;
}

.snapshot-title {
  font-size: 13px;
  font-weight: 650;
  color: var(--app-muted);
}

.snapshot-kv-list {
  display: grid;
  gap: 7px;
}

.snapshot-kv {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
  padding-bottom: 6px;
  border-bottom: 1px dashed rgba(148, 163, 184, 0.14);
}

.snapshot-kv:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.snapshot-kv span {
  color: var(--app-muted);
  flex: 0 0 auto;
}

.snapshot-kv strong {
  color: var(--app-text);
  font-weight: 550;
  text-align: right;
  word-break: break-word;
}

.files-card-header {
  justify-content: space-between;
}

.issue-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

@media (max-width: 1024px) {
  .detail-overview-grid {
    grid-template-columns: 1fr;
  }

  .detail-stats-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .detail-stats-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
