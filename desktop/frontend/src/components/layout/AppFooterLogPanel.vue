<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ChevronDown, ChevronUp, Terminal, Trash2 } from 'lucide-vue-next'
import StatusTag from '../common/StatusTag.vue'
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
  if (!activeTaskId.value) return '点击任意任务即可绑定实时日志流'
  return selectedTask.value ? taskDisplayName(selectedTask.value) : activeTaskId.value
})
const taskStatus = computed(() => taskStatusLabel(selectedTask.value))

async function ensureTaskBound() {
  if (!activeTaskId.value) return
  if (selectedTaskId.value !== activeTaskId.value) {
    await selectTask(activeTaskId.value, { includeLogs: footerExpanded.value, includeResources: false })
  } else if (footerExpanded.value) {
    await refreshLogs()
  }
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

const polling = usePolling(ensureTaskBound, 2500, { hiddenIntervalMs: 15000 })

onMounted(() => polling.start())
</script>

<template>
  <footer
    class="footer-log-panel"
    :class="{ collapsed: !footerExpanded }"
    :style="{ height: `${footerExpanded ? footerHeight : 40}px` }"
  >
    <div class="footer-log-titlebar">
      <div
        class="footer-log-title"
        role="button"
        :aria-expanded="footerExpanded"
        tabindex="0"
        @click="setFooterExpanded(!footerExpanded)"
        @keydown.enter="setFooterExpanded(!footerExpanded)"
      >
        <Terminal :size="14" class="footer-console-icon" />
        <strong>实时控制台</strong>
        <span class="footer-task-label">{{ taskLabel }}</span>
        <StatusTag v-if="selectedTask" :status="selectedTask.status" :label="taskStatus" />
      </div>

      <div class="footer-log-actions">
        <el-switch
          v-if="footerExpanded"
          :model-value="logAutoScroll"
          size="small"
          active-text="跟随输出"
          @change="setLogAutoScroll(Boolean($event))"
        />
        <el-button v-if="footerExpanded" size="small" text @click="clearDisplayLogs">
          <Trash2 :size="13" style="margin-right: 4px" />清屏
        </el-button>
        <el-button
          class="footer-toggle-button"
          circle
          :aria-label="footerExpanded ? '收起日志' : '展开日志'"
          @click="setFooterExpanded(!footerExpanded)"
        >
          <ChevronDown v-if="footerExpanded" :size="15" />
          <ChevronUp v-else :size="15" />
        </el-button>
      </div>
    </div>

    <div v-show="footerExpanded" ref="logBody" class="footer-log-body" aria-live="polite">
      <div v-if="!activeTaskId" class="footer-log-empty">在任务中心点击或打开任意任务，即可在此实时追踪执行日志。</div>
      <div v-else-if="!visibleLogs.length" class="footer-log-empty">等待任务输出实时日志…</div>
      <p v-for="line in visibleLogs" v-else :key="line.id" class="footer-log-line" :data-level="line.level">
        <time>{{ line.created_at }}</time>
        <span class="level">{{ (line.level || 'info').toUpperCase() }}</span>
        <span>{{ line.message }}</span>
      </p>
    </div>
  </footer>
</template>
