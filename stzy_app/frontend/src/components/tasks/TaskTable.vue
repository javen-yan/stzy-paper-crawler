<script setup lang="ts">
import { Archive, ChevronRight, CirclePause, CirclePlay, Eye, MoreHorizontal, XCircle } from 'lucide-vue-next'
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

function canResume(status: string) {
  return RESUMABLE.includes(status)
}

function canPause(status: string) {
  return PAUSABLE.includes(status)
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
          <button class="task-title-btn" @click.stop="$emit('view', task)">
            <span class="task-title">{{ taskDisplayName(task, index) }}</span>
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
          <el-tooltip content="详情" placement="top">
            <el-button class="task-icon-btn" :icon="Eye" circle aria-label="详情" @click="$emit('view', task)" />
          </el-tooltip>
          <el-tooltip content="暂停" placement="top">
            <el-button class="task-icon-btn" :icon="CirclePause" circle aria-label="暂停" :disabled="!canPause(task.status)" @click="$emit('action', task, 'pause')" />
          </el-tooltip>
          <el-tooltip content="恢复" placement="top">
            <el-button class="task-icon-btn" :icon="CirclePlay" circle aria-label="恢复" :disabled="!canResume(task.status)" @click="$emit('action', task, 'resume')" />
          </el-tooltip>
          <el-dropdown trigger="click">
            <el-button class="task-icon-btn" :icon="MoreHorizontal" circle aria-label="更多操作" />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :icon="Archive" @click="$emit('action', task, 'archive')">归档</el-dropdown-item>
                <el-dropdown-item :icon="XCircle" @click="$emit('action', task, 'cancel')">取消任务</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <ChevronRight class="task-chevron" :size="18" aria-hidden="true" />
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
  grid-template-columns: 4px minmax(0, 1fr) auto 20px;
  gap: 16px;
  align-items: center;
  padding: 14px 16px 14px 0;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  cursor: pointer;
  overflow: hidden;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease, background 160ms ease;
}

.task-card:hover {
  border-color: rgba(97, 175, 239, 0.4);
  background: var(--app-surface-2);
  box-shadow: var(--app-glow-soft);
  transform: translateX(2px);
}

.task-card.is-selected {
  border-color: rgba(97, 175, 239, 0.6);
  box-shadow: var(--app-glow-soft);
}

.task-card:focus-visible {
  outline: 1px solid var(--app-primary);
  outline-offset: 2px;
}

.status-rail {
  width: 4px;
  height: 100%;
  background: #475569;
}

[data-tone="active"] .status-rail {
  background: var(--app-primary);
  box-shadow: 0 0 12px var(--app-primary);
}

[data-tone="success"] .status-rail {
  background: var(--app-accent);
  box-shadow: 0 0 12px var(--app-accent);
}

[data-tone="warning"] .status-rail {
  background: var(--app-warning);
  box-shadow: 0 0 12px var(--app-warning);
}

[data-tone="danger"] .status-rail {
  background: var(--app-danger);
  box-shadow: 0 0 12px var(--app-danger);
}

.task-main {
  display: grid;
  gap: 10px;
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
  gap: 3px;
  border: 0;
  background: transparent;
  padding: 0;
  text-align: left;
  cursor: pointer;
  min-width: 0;
}

.task-title {
  color: var(--app-text);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 160ms ease, text-shadow 160ms ease;
}

.task-card:hover .task-title {
  color: var(--app-primary);
  text-shadow: 0 0 12px rgba(97, 175, 239, 0.5);
}

.task-id {
  font-size: 11px;
  color: var(--app-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-progress-row {
  max-width: 520px;
}

.task-side {
  display: grid;
  gap: 8px;
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
  border-color: var(--app-border);
  color: var(--app-muted);
  background: var(--app-bg-2);
  opacity: 0.6;
  transition: opacity 160ms ease, border-color 160ms ease, color 160ms ease, background 160ms ease;
}

.task-card:hover .task-icon-btn.el-button {
  opacity: 1;
}

.task-icon-btn.el-button:hover {
  border-color: rgba(97, 175, 239, 0.4);
  color: var(--app-primary);
  background: var(--app-primary-soft);
}

.task-chevron {
  color: var(--app-faint);
  opacity: 0;
  transition: opacity 160ms ease, color 160ms ease, transform 160ms ease;
}

.task-card:hover .task-chevron {
  opacity: 1;
  color: var(--app-primary);
  transform: translateX(2px);
}

@media (max-width: 760px) {
  .task-card {
    grid-template-columns: 4px minmax(0, 1fr);
    padding-right: 12px;
  }

  .task-side,
  .task-chevron {
    display: none;
  }
}
</style>
