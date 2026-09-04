<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import TaskCreateWizard from '../components/tasks/TaskCreateWizard.vue'
import TaskSummaryCards from '../components/tasks/TaskSummaryCards.vue'
import TaskTable from '../components/tasks/TaskTable.vue'
import EmptyState from '../components/common/EmptyState.vue'
import SimplePager from '../components/common/SimplePager.vue'
import { listAccounts } from '../api/accounts'
import { useLayoutState } from '../composables/useLayoutState'
import { usePolling } from '../composables/usePolling'
import { useTasks } from '../composables/useTasks'
import { useToast } from '../composables/useToast'
import type { Account } from '../types/accounts'
import type { Task, TaskCreateForm } from '../types/tasks'

const router = useRouter()
const toast = useToast()
const { setActiveTaskId } = useLayoutState()
const { tasks, selectedTaskId, refreshTasks, selectTask, submitTask, runTaskAction } = useTasks()
const accounts = ref<Account[]>([])
const loading = ref(false)
const submitting = ref(false)
const page = ref(1)
const pageSize = ref(20)
const hasNextPage = ref(false)
let accountRefreshAt = 0

const visibleTasks = computed(() => tasks.value.slice(0, pageSize.value))

async function refresh(options: { includeAccounts?: boolean } = {}) {
  const payload = await refreshTasks({ limit: pageSize.value + 1, offset: (page.value - 1) * pageSize.value })
  hasNextPage.value = payload.items.length > pageSize.value
  if (selectedTaskId.value) setActiveTaskId(selectedTaskId.value)
  if (options.includeAccounts || Date.now() - accountRefreshAt > 30000) {
    accounts.value = (await listAccounts()).items
    accountRefreshAt = Date.now()
  }
}

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
    const task = await submitTask(form)
    setActiveTaskId(task.id)
    toast.success('下载任务已创建')
  } catch (error) {
    toast.error(error, '任务提交失败')
  } finally {
    submitting.value = false
  }
}

async function handleSelect(task: Task) {
  setActiveTaskId(task.id)
  await selectTask(task.id, { includeLogs: false, includeResources: false })
}

async function handleAction(task: Task, action: 'pause' | 'resume' | 'cancel' | 'archive') {
  if (['cancel', 'archive'].includes(action)) {
    await ElMessageBox.confirm(action === 'cancel' ? '取消后任务会停止调度，在途操作会收尾。' : '归档只隐藏任务，不删除文件。', '确认操作', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
  }
  try {
    await runTaskAction(task.id, action)
    toast.success('操作已提交')
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
        <p class="eyebrow">创建任务、查看进度</p>
        <h2>任务中心</h2>
      </div>
      <div class="hero-actions">
      <TaskCreateWizard :accounts="accounts" :submitting="submitting" @submit="handleSubmit" />
      </div>
    </section>

    <TaskSummaryCards :tasks="visibleTasks" />

    <el-card shadow="never" class="task-list-card">
      <template #header>
        <div class="card-header">
          <span>任务列表</span>
          <span class="task-count mono">第 {{ page }} 页 · {{ visibleTasks.length }} 个任务</span>
        </div>
      </template>
      <el-skeleton v-if="loading" :rows="5" animated />
      <EmptyState
        v-else-if="!tasks.length"
        title="还没有下载任务"
        description="点击右上角「新建下载任务」开始。"
      />
      <template v-else>
        <TaskTable :tasks="visibleTasks" :selected-task-id="selectedTaskId" @select="handleSelect" @view="router.push(`/tasks/${$event.id}`)" @action="handleAction" />
        <SimplePager
          class="list-pager"
          :page="page"
          :page-size="pageSize"
          :item-count="visibleTasks.length"
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
  padding: 14px 16px;
  border-bottom: 1px solid var(--app-border);
}

.task-list-card :deep(.el-card__body) {
  padding: 16px;
}

.task-count {
  color: var(--app-primary);
  font-size: 12px;
  padding: 2px 10px;
  border: 1px solid rgba(97, 175, 239, 0.3);
  border-radius: 999px;
  background: var(--app-primary-soft);
}

@media (max-width: 760px) {
  .task-center-hero .hero-actions,
  .task-center-hero .hero-actions :deep(.el-button) {
    width: 100%;
  }
}
</style>
