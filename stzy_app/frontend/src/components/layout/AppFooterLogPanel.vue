<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Delete } from '@element-plus/icons-vue'
import { useLayoutState } from '../../composables/useLayoutState'
import { usePolling } from '../../composables/usePolling'
import { taskStatusLabel, useTasks } from '../../composables/useTasks'
import { taskDisplayName } from '../../utils/taskDisplay'

const {
  activeTaskId,
  footerExpanded,
  footerHeight,
  logAutoScroll,
  setFooterExpanded,
  setLogAutoScroll,
} = useLayoutState()
const { selectedTaskId, selectedTask, logs, selectTask, refreshLogs } = useTasks()
const logBody = ref<HTMLElement | null>(null)
const localClearedBefore = ref(0)

const visibleLogs = computed(() => logs.value.filter((line) => line.id > localClearedBefore.value))
const taskLabel = computed(() => {
  if (!activeTaskId.value) return '未选择任务'
  return selectedTask.value ? taskDisplayName(selectedTask.value) : activeTaskId.value
})
const taskStatus = computed(() => taskStatusLabel(selectedTask.value))

async function ensureTaskBound() {
  if (!activeTaskId.value) return
  if (selectedTaskId.value !== activeTaskId.value) await selectTask(activeTaskId.value, { includeLogs: footerExpanded.value, includeResources: false })
  else if (footerExpanded.value) await refreshLogs()
}

function clearDisplayLogs() {
  localClearedBefore.value = logs.value[logs.value.length - 1]?.id || 0
}

function scrollToBottom() {
  if (!logAutoScroll.value || !logBody.value) return
  logBody.value.scrollTop = logBody.value.scrollHeight
}

watch(
  () => activeTaskId.value,
  async () => {
    localClearedBefore.value = 0
    await ensureTaskBound()
    await nextTick()
    scrollToBottom()
  },
)

watch(
  () => visibleLogs.value.length,
  async () => {
    await nextTick()
    scrollToBottom()
  },
)

watch(
  () => footerExpanded.value,
  async (expanded) => {
    if (!expanded) return
    await ensureTaskBound()
    await nextTick()
    scrollToBottom()
  },
)

const polling = usePolling(ensureTaskBound, 2000, { hiddenIntervalMs: 15000 })

onMounted(() => polling.start())
</script>

<template>
  <footer class="footer-log-panel" :class="{ collapsed: !footerExpanded }" :style="{ height: `${footerExpanded ? footerHeight : 44}px` }">
    <div class="footer-log-titlebar">
      <div class="footer-log-title" role="button" :aria-expanded="footerExpanded" tabindex="0" @click="setFooterExpanded(!footerExpanded)" @keydown.enter="setFooterExpanded(!footerExpanded)">
        <strong>运行日志</strong>
        <span>{{ taskLabel }}</span>
        <el-tag size="small">{{ taskStatus }}</el-tag>
      </div>
      <div class="footer-log-actions">
        <el-switch
          v-if="footerExpanded"
          :model-value="logAutoScroll"
          size="small"
          active-text="自动滚动"
          inactive-text="暂停滚动"
          @change="setLogAutoScroll(Boolean($event))"
        />
        <el-button v-if="footerExpanded" size="small" :icon="Delete" text @click="clearDisplayLogs">清屏</el-button>
        <el-tooltip :content="footerExpanded ? '关闭日志' : '打开日志'" placement="top">
          <el-button
            class="footer-toggle-button"
            :icon="footerExpanded ? ArrowDown : ArrowUp"
            circle
            :aria-label="footerExpanded ? '关闭日志' : '打开日志'"
            @click="setFooterExpanded(!footerExpanded)"
          />
        </el-tooltip>
      </div>
    </div>

    <div v-show="footerExpanded" ref="logBody" class="footer-log-body" aria-live="polite">
      <div v-if="!activeTaskId" class="footer-log-empty">选择任务后显示运行日志。</div>
      <div v-else-if="!visibleLogs.length" class="footer-log-empty">暂无日志。</div>
      <p v-for="line in visibleLogs" v-else :key="line.id" class="footer-log-line" :data-level="line.level">
        <time>{{ line.created_at }}</time>
        <span class="level">[{{ line.level || 'info' }}]</span>
        <span>{{ line.message }}</span>
      </p>
    </div>
  </footer>
</template>
