<script setup lang="ts">
import { Archive, ArrowUpRight, CirclePause, CirclePlay, Download, FolderOpen, MoreHorizontal, XCircle } from 'lucide-vue-next'
import StatusTag from '../common/StatusTag.vue'
import TaskProgress from './TaskProgress.vue'
import type { Task } from '../../types/tasks'
import { taskStatusLabel } from '../../composables/useTasks'
import { taskDisplayName } from '../../utils/taskDisplay'

defineProps<{ tasks: Task[]; selectedTaskId?: string }>()
defineEmits<{
  select: [task: Task]
  action: [task: Task, action: 'pause' | 'resume' | 'cancel' | 'archive']
  view: [task: Task]
  openFolder: [task: Task]
  startDownload: [task: Task]
}>()

function statusTone(status: string) {
  if (status === 'completed') return 'success'
  if (['failed', 'auth_expired', 'cancelled', 'interrupted'].includes(status)) return 'danger'
  if (['paused', 'pausing', 'partial_completed'].includes(status)) return 'warning'
  if (status === 'running') return 'active'
  return 'idle'
}

const RESUMABLE = ['paused', 'partial_completed', 'failed', 'auth_expired', 'interrupted', 'cancelled']
const PAUSABLE = ['running', 'queued']

function canResume(task: Task) {
  return task.mode !== 'estimate' && RESUMABLE.includes(task.status)
}

function canPause(task: Task) {
  return PAUSABLE.includes(task.status)
}

function canOpenFolder(task: Task) {
  if (task.mode === 'estimate') return false
  const completedCount = Number(task.stats?.resources_completed || task.stats?.resources_success || 0)
  return completedCount > 0 || ['completed', 'partial_completed'].includes(task.status)
}

function canConvertEstimate(task: Task) {
  return task.mode === 'estimate' && task.status === 'completed'
}

function formatShortTime(raw?: string) {
  if (!raw) return ''
  const cleaned = raw.replace('T', ' ').replace(/\.\d+/, '').replace(/([+-]\d{2}:\d{2}|Z)$/, '')
  return cleaned.length >= 16 ? cleaned.slice(5, 16) : cleaned
}

function shouldShowError(task: Task) {
  return Boolean(task.error && ['failed', 'auth_expired', 'interrupted'].includes(task.status))
}
</script>

<template>
  <div class="task-list">
    <article
      v-for="(task, index) in tasks"
      :key="task.id"
      class="task-card"
      :class="{ 'is-selected': task.id === selectedTaskId }"
      :data-tone="statusTone(task.status)"
      tabindex="0"
      @click="$emit('view', task)"
      @keydown.enter="$emit('view', task)"
    >
      <span class="status-rail" aria-hidden="true" />

      <div class="task-main">
        <div class="task-head">
          <div class="task-title-line">
            <span class="task-mode-pill" :class="{ estimate: task.mode === 'estimate' }">
              {{ task.mode === 'estimate' ? '预估' : '下载' }}
            </span>
            <span class="task-title">{{ taskDisplayName(task, index) }}</span>
            <StatusTag :status="task.status" :label="taskStatusLabel(task)" />
          </div>
          <span v-if="shouldShowError(task)" class="task-error-inline" :title="task.error">
            {{ task.error }}
          </span>
        </div>

        <div class="task-progress-row">
          <TaskProgress :task="task" />
        </div>
      </div>

      <div class="task-side">
        <time class="task-time mono">{{ formatShortTime(task.updated_at) }}</time>
        <div class="task-actions" @click.stop>
          <el-button
            v-if="canConvertEstimate(task)"
            size="small"
            type="primary"
            plain
            @click="$emit('startDownload', task)"
          >
            <Download :size="13" style="margin-right: 4px" />开始下载
          </el-button>

          <el-tooltip v-if="canOpenFolder(task)" content="打开本地保存目录" placement="top">
            <el-button
              class="task-icon-btn"
              circle
              aria-label="打开本地保存目录"
              @click="$emit('openFolder', task)"
            >
              <FolderOpen :size="14" />
            </el-button>
          </el-tooltip>

          <el-button
            v-if="canPause(task)"
            size="small"
            class="task-action-btn"
            @click="$emit('action', task, 'pause')"
          >
            <CirclePause :size="13" style="margin-right: 4px" />暂停
          </el-button>

          <el-button
            v-if="canResume(task)"
            size="small"
            type="primary"
            plain
            class="task-action-btn"
            @click="$emit('action', task, 'resume')"
          >
            <CirclePlay :size="13" style="margin-right: 4px" />继续
          </el-button>

          <el-dropdown v-if="!task.archived || canPause(task)" trigger="click">
            <el-button class="task-icon-btn" :icon="MoreHorizontal" circle aria-label="更多操作" />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="canPause(task)" :icon="XCircle" @click="$emit('action', task, 'cancel')">
                  取消任务
                </el-dropdown-item>
                <el-dropdown-item v-if="!task.archived" :icon="Archive" @click="$emit('action', task, 'archive')">
                  归档隐藏
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-button class="task-detail-pill" size="small" @click="$emit('view', task)">
            详情 <ArrowUpRight :size="13" style="margin-left: 2px" />
          </el-button>
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.task-list {
  display: grid;
  gap: 10px;
}

.task-card {
  position: relative;
  display: grid;
  grid-template-columns: 4px minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  padding: 14px 16px 14px 0;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: rgba(16, 23, 38, 0.72);
  cursor: pointer;
  overflow: hidden;
  transition: border-color 160ms ease, box-shadow 160ms ease, background-color 160ms ease;
}

.task-card:hover {
  border-color: rgba(129, 140, 248, 0.44);
  background: rgba(23, 33, 54, 0.88);
  box-shadow: 0 8px 22px -8px rgba(2, 6, 23, 0.55);
}

.task-card.is-selected {
  border-color: rgba(129, 140, 248, 0.62);
  background: rgba(25, 36, 58, 0.92);
}

.task-card:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 2px;
}

.status-rail {
  width: 4px;
  height: 100%;
  border-radius: 0 4px 4px 0;
  background: rgba(148, 163, 184, 0.35);
}

[data-tone="active"] .status-rail {
  background: linear-gradient(180deg, #818cf8, #38bdf8);
}

[data-tone="success"] .status-rail {
  background: linear-gradient(180deg, #34d399, #10b981);
}

[data-tone="warning"] .status-rail {
  background: linear-gradient(180deg, #fbbf24, #f59e0b);
}

[data-tone="danger"] .status-rail {
  background: linear-gradient(180deg, #fb7185, #f43f5e);
}

.task-main {
  display: grid;
  gap: 9px;
  min-width: 0;
}

.task-head {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.task-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.task-mode-pill {
  flex: 0 0 auto;
  height: 20px;
  padding: 0 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  line-height: 20px;
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.16);
  border: 1px solid rgba(129, 140, 248, 0.24);
}

.task-mode-pill.estimate {
  color: #7dd3fc;
  background: rgba(14, 165, 233, 0.14);
  border-color: rgba(56, 189, 248, 0.24);
}

.task-title {
  color: var(--app-text);
  font-size: 14.5px;
  font-weight: 620;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: min(560px, 60vw);
}

.task-card:hover .task-title {
  color: #c7d2fe;
}

.task-error-inline {
  font-size: 12px;
  color: var(--app-danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-progress-row {
  max-width: 560px;
}

.task-side {
  display: grid;
  gap: 8px;
  justify-items: end;
}

.task-time {
  font-size: 12px;
  color: var(--app-faint);
}

.task-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.task-action-btn.el-button {
  height: 30px;
  padding: 0 10px;
  border-radius: 8px;
}

.task-icon-btn.el-button {
  width: 30px;
  height: 30px;
  min-height: 30px;
  padding: 0;
  border-radius: 8px;
  border-color: var(--app-border);
  color: var(--app-muted);
  background: rgba(15, 23, 42, 0.72);
}

.task-icon-btn.el-button:hover:not(.is-disabled) {
  border-color: rgba(129, 140, 248, 0.45);
  color: var(--app-primary);
  background: var(--app-primary-soft);
}

.task-detail-pill.el-button {
  height: 30px;
  min-height: 30px;
  padding: 0 10px;
  border-radius: 8px;
  border-color: rgba(129, 140, 248, 0.28);
  background: rgba(99, 102, 241, 0.12);
  color: #c7d2fe;
  font-size: 12px;
}

.task-detail-pill.el-button:hover {
  border-color: rgba(129, 140, 248, 0.55);
  background: rgba(99, 102, 241, 0.24);
  color: #ffffff;
}

@media (max-width: 760px) {
  .task-card {
    grid-template-columns: 4px minmax(0, 1fr);
    padding-right: 14px;
  }

  .task-side {
    display: none;
  }
}
</style>
