<script setup lang="ts">
import { Archive, ArrowUpRight, CirclePause, CirclePlay, MoreHorizontal, Terminal, XCircle } from 'lucide-vue-next'
import StatusTag from '../common/StatusTag.vue'
import TaskProgress from './TaskProgress.vue'
import type { Task } from '../../types/tasks'
import { useLayoutState } from '../../composables/useLayoutState'
import { taskStatusLabel } from '../../composables/useTasks'
import { taskDisplayName } from '../../utils/taskDisplay'

defineProps<{ tasks: Task[]; selectedTaskId?: string }>()
const emit = defineEmits<{
  select: [task: Task]
  action: [task: Task, action: 'pause' | 'resume' | 'cancel' | 'archive']
  view: [task: Task]
}>()

const { setFooterExpanded } = useLayoutState()

function statusTone(status: string) {
  if (status === 'completed') return 'success'
  if (['failed', 'auth_expired', 'cancelled', 'interrupted'].includes(status)) return 'danger'
  if (['paused', 'pausing', 'partial_completed'].includes(status)) return 'warning'
  if (status === 'running') return 'active'
  return 'idle'
}

const RESUMABLE = ['paused', 'partial_completed', 'failed', 'auth_expired', 'interrupted', 'cancelled']
const PAUSABLE = ['running', 'queued']

function canResume(status: string) {
  return RESUMABLE.includes(status)
}

function canPause(status: string) {
  return PAUSABLE.includes(status)
}

function openLiveConsole(task: Task) {
  emit('select', task)
  setFooterExpanded(true)
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
          <button type="button" class="task-title-btn" @click.stop="$emit('view', task)">
            <span class="task-title-line">
              <span class="task-mode-pill" :class="{ estimate: task.mode === 'estimate' }">
                {{ task.mode === 'estimate' ? '数量预估' : '采集下载' }}
              </span>
              <span class="task-title">{{ taskDisplayName(task, index) }}</span>
            </span>
            <span class="task-id mono">#{{ task.id }}</span>
          </button>
          <StatusTag :status="task.status" :label="taskStatusLabel(task)" />
        </div>

        <div class="task-progress-row">
          <TaskProgress :task="task" />
        </div>
      </div>

      <div class="task-side">
        <time class="task-time mono">{{ task.updated_at }}</time>
        <div class="task-actions" @click.stop>
          <el-tooltip content="实时日志" placement="top">
            <el-button class="task-icon-btn" circle aria-label="实时日志" @click="openLiveConsole(task)">
              <Terminal :size="14" />
            </el-button>
          </el-tooltip>
          <el-tooltip content="暂停任务" placement="top">
            <el-button
              class="task-icon-btn"
              :icon="CirclePause"
              circle
              aria-label="暂停"
              :disabled="!canPause(task.status)"
              @click="$emit('action', task, 'pause')"
            />
          </el-tooltip>
          <el-tooltip content="恢复执行" placement="top">
            <el-button
              class="task-icon-btn"
              :icon="CirclePlay"
              circle
              aria-label="恢复"
              :disabled="!canResume(task.status)"
              @click="$emit('action', task, 'resume')"
            />
          </el-tooltip>
          <el-dropdown trigger="click">
            <el-button class="task-icon-btn" :icon="MoreHorizontal" circle aria-label="更多操作" />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :icon="Archive" @click="$emit('action', task, 'archive')">归档任务</el-dropdown-item>
                <el-dropdown-item :icon="XCircle" @click="$emit('action', task, 'cancel')">取消任务</el-dropdown-item>
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
  gap: 18px;
  align-items: center;
  padding: 16px 18px 16px 0;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: rgba(16, 23, 38, 0.72);
  cursor: pointer;
  overflow: hidden;
  transition: border-color 170ms ease, box-shadow 170ms ease, transform 170ms cubic-bezier(0.22, 1, 0.36, 1), background-color 170ms ease;
}

.task-card:hover {
  border-color: rgba(129, 140, 248, 0.42);
  background: rgba(23, 33, 54, 0.88);
  box-shadow: 0 10px 26px -8px rgba(2, 6, 23, 0.6);
  transform: translateY(-1px);
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
  gap: 11px;
  min-width: 0;
}

.task-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.task-title-btn {
  display: grid;
  gap: 4px;
  border: 0;
  background: transparent;
  padding: 0;
  text-align: left;
  cursor: pointer;
  min-width: 0;
}

.task-title-line {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
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
  font-size: 15px;
  font-weight: 620;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 160ms ease;
}

.task-card:hover .task-title {
  color: #c7d2fe;
}

.task-id {
  font-size: 11.5px;
  color: var(--app-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-progress-row {
  max-width: 560px;
}

.task-side {
  display: grid;
  gap: 9px;
  justify-items: end;
}

.task-time {
  font-size: 12px;
  color: var(--app-muted);
}

.task-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.task-icon-btn.el-button {
  width: 32px;
  height: 32px;
  min-height: 32px;
  padding: 0;
  border-radius: 8px;
  border-color: var(--app-border);
  color: var(--app-muted);
  background: rgba(15, 23, 42, 0.72);
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

.task-icon-btn.el-button:hover:not(.is-disabled) {
  border-color: rgba(129, 140, 248, 0.45);
  color: var(--app-primary);
  background: var(--app-primary-soft);
}

.task-detail-pill.el-button {
  height: 32px;
  min-height: 32px;
  padding: 0 11px;
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
