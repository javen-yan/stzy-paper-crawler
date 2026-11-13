<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { FolderOutput, Search } from 'lucide-vue-next'
import TaskCreateWizard from '../components/tasks/TaskCreateWizard.vue'
import TaskSummaryCards, { type TaskQuickFilter } from '../components/tasks/TaskSummaryCards.vue'
import TaskTable from '../components/tasks/TaskTable.vue'
import EmptyState from '../components/common/EmptyState.vue'
import SimplePager from '../components/common/SimplePager.vue'
import { listAccounts } from '../api/accounts'
import { openLocalPath } from '../api/local'
import { useLayoutState } from '../composables/useLayoutState'
import { usePolling } from '../composables/usePolling'
import { useTasks } from '../composables/useTasks'
import { useToast } from '../composables/useToast'
import { taskDisplayName } from '../utils/taskDisplay'
import type { Account } from '../types/accounts'
import type { Task, TaskCreateForm } from '../types/tasks'

const router = useRouter()
const toast = useToast()
const { setActiveTaskId } = useLayoutState()
const { tasks, selectedTaskId, refreshTasks, selectTask, submitTask, createDownloadFromEstimate, runTaskAction } = useTasks()
const accounts = ref<Account[]>([])
const loading = ref(false)
const submitting = ref(false)
const quickFilter = ref<TaskQuickFilter>('all')
const searchKeyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const hasNextPage = ref(false)
let accountRefreshAt = 0

const filterTabs: Array<{ key: TaskQuickFilter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '进行中' },
  { key: 'completed', label: '已完成' },
  { key: 'attention', label: '异常 / 暂停' },
  { key: 'archived', label: '已归档' },
]

const rawPageTasks = computed(() => tasks.value.slice(0, pageSize.value))

const filteredTasks = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  return rawPageTasks.value.filter((task, idx) => {
    if (quickFilter.value === 'active' && !['running', 'queued', 'pausing'].includes(task.status)) {
      return false
    }
    if (quickFilter.value === 'completed' && task.status !== 'completed') {
      return false
    }
    if (
      quickFilter.value === 'attention' &&
      !['failed', 'auth_expired', 'interrupted', 'partial_completed', 'paused'].includes(task.status)
    ) {
      return false
    }
    if (kw) {
      const name = taskDisplayName(task, idx).toLowerCase()
      const id = String(task.id || '').toLowerCase()
      if (!name.includes(kw) && !id.includes(kw)) return false
    }
    return true
  })
})

async function refresh(options: { includeAccounts?: boolean } = {}) {
  const showArchived = quickFilter.value === 'archived'
  const payload = await refreshTasks({
    archived: showArchived,
    limit: pageSize.value + 1,
    offset: (page.value - 1) * pageSize.value,
  })
  hasNextPage.value = payload.items.length > pageSize.value
  if (selectedTaskId.value) setActiveTaskId(selectedTaskId.value)
  if (options.includeAccounts || Date.now() - accountRefreshAt > 30000) {
    accounts.value = (await listAccounts()).items
    accountRefreshAt = Date.now()
  }
}

watch(
  () => quickFilter.value,
  async (next, prev) => {
    page.value = 1
    if (next === 'archived' || prev === 'archived') {
      await refresh()
    }
  },
)

async function changePageSize(value: number) {
  pageSize.value = value
  page.value = 1
  await refresh()
}

async function prevPage() {
  if (page.value <= 1) return
  page.value -= 1
  await refresh()
}

async function nextPage() {
  if (!hasNextPage.value) return
  page.value += 1
  await refresh()
}

async function handleSubmit(form: TaskCreateForm) {
  submitting.value = true
  try {
    if (quickFilter.value === 'archived') {
      quickFilter.value = 'all'
    }
    const task = await submitTask(form)
    setActiveTaskId(task.id)
    toast.success('下载任务已加入队列')
  } catch (error) {
    toast.error(error, '任务创建失败')
  } finally {
    submitting.value = false
  }
}

async function handleSelect(task: Task) {
  setActiveTaskId(task.id)
  await selectTask(task.id, { includeLogs: false, includeResources: false })
}

async function handleOpenFolder(task: Task) {
  try {
    await openLocalPath('', { taskId: task.id })
  } catch (error) {
    toast.error(error, '打开保存目录失败')
  }
}

async function handleOpenRootFolder() {
  try {
    await openLocalPath('')
  } catch (error) {
    toast.error(error, '打开输出目录失败')
  }
}

async function handleStartFromEstimate(task: Task) {
  try {
    const created = await createDownloadFromEstimate(task)
    setActiveTaskId(created.id)
    toast.success('已按预估条件创建下载任务')
  } catch (error) {
    toast.error(error, '创建下载任务失败')
  }
}

async function handleAction(task: Task, action: 'pause' | 'resume' | 'cancel' | 'archive') {
  if (['cancel', 'archive'].includes(action)) {
    try {
      await ElMessageBox.confirm(
        action === 'cancel' ? '取消后任务停止下载，已完成的文件会保留。' : '归档后任务移至「已归档」列表，本地已下载的文件不会删除。',
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
  try {
    await runTaskAction(task.id, action)
    await refresh()
    toast.success(action === 'archive' ? '已归档' : '操作已执行')
  } catch (error) {
    toast.error(error)
  }
}

const polling = usePolling(refresh, 3000, { hiddenIntervalMs: 15000 })

onMounted(async () => {
  loading.value = true
  try {
    await refresh({ includeAccounts: true })
    polling.start()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page-stack">
    <section class="page-hero task-center-hero">
      <div>
        <h2>任务管理</h2>
        <p class="hero-subtitle">按条件筛选下载试卷，支持断点续传与本地一键打开。</p>
      </div>
      <div class="hero-actions">
        <el-button size="large" @click="handleOpenRootFolder">
          <FolderOutput :size="16" style="margin-right: 6px" />打开下载目录
        </el-button>
        <TaskCreateWizard :accounts="accounts" :submitting="submitting" @submit="handleSubmit" />
      </div>
    </section>

    <TaskSummaryCards
      v-if="quickFilter !== 'archived'"
      :model-value="quickFilter"
      :tasks="rawPageTasks"
      @update:model-value="quickFilter = $event"
    />

    <el-card shadow="never" class="task-list-card">
      <template #header>
        <div class="task-toolbar">
          <div class="filter-tabs" role="tablist">
            <button
              v-for="tab in filterTabs"
              :key="tab.key"
              type="button"
              class="filter-tab-btn"
              :class="{ active: quickFilter === tab.key }"
              @click="quickFilter = tab.key"
            >
              {{ tab.label }}
            </button>
          </div>

          <div class="toolbar-right">
            <el-input
              v-model="searchKeyword"
              size="small"
              clearable
              placeholder="搜索任务名称…"
              class="task-search-input"
            >
              <template #prefix><Search :size="13" /></template>
            </el-input>
            <span class="task-count mono">{{ filteredTasks.length }} 项</span>
          </div>
        </div>
      </template>

      <el-skeleton v-if="loading" :rows="5" animated />
      <EmptyState
        v-else-if="!rawPageTasks.length"
        :title="quickFilter === 'archived' ? '暂无已归档任务' : '暂无下载任务'"
        :description="quickFilter === 'archived' ? '归档后的历史任务会显示在这里。' : '点击右上角「新建下载任务」选择学科与地区开始下载。'"
      />
      <EmptyState
        v-else-if="!filteredTasks.length"
        title="没有匹配当前筛选的任务"
        description="可以切换上方状态标签或清空搜索关键词。"
        action-text="查看全部任务"
        @action="quickFilter = 'all'; searchKeyword = ''"
      />
      <template v-else>
        <TaskTable
          :tasks="filteredTasks"
          :selected-task-id="selectedTaskId"
          @select="handleSelect"
          @view="router.push(`/tasks/${$event.id}`)"
          @action="handleAction"
          @open-folder="handleOpenFolder"
          @start-download="handleStartFromEstimate"
        />
        <SimplePager
          class="list-pager"
          :page="page"
          :page-size="pageSize"
          :item-count="rawPageTasks.length"
          :has-next="hasNextPage"
          :loading="loading"
          label="任务"
          @prev="prevPage"
          @next="nextPage"
          @refresh="refresh"
          @page-size-change="changePageSize"
        />
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.task-list-card :deep(.el-card__header) {
  padding: 12px 16px;
  border-bottom: 1px solid var(--app-border);
}

.task-list-card :deep(.el-card__body) {
  padding: 16px;
}

.task-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-tabs {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px;
  border-radius: 9px;
  background: rgba(9, 13, 22, 0.72);
  border: 1px solid var(--app-border);
}

.filter-tab-btn {
  height: 28px;
  padding: 0 12px;
  border-radius: 7px;
  border: 0;
  background: transparent;
  color: var(--app-muted);
  font-size: 12.5px;
  font-weight: 550;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.filter-tab-btn:hover {
  color: var(--app-text);
}

.filter-tab-btn.active {
  background: rgba(99, 102, 241, 0.24);
  color: #ffffff;
  font-weight: 600;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-search-input {
  width: 210px;
}

.task-count {
  color: var(--app-muted);
  font-size: 12px;
  padding: 2px 10px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.6);
}

@media (max-width: 760px) {
  .task-center-hero .hero-actions {
    width: 100%;
  }

  .task-search-input {
    width: 100%;
  }
}
</style>
