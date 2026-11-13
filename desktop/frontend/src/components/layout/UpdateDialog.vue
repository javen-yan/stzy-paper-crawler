<script setup lang="ts">
import { computed } from 'vue'
import { Download, ExternalLink, Sparkles } from 'lucide-vue-next'
import { openExternalUrl } from '../../api/local'
import { useTasks } from '../../composables/useTasks'
import { useToast } from '../../composables/useToast'
import { useUpdater } from '../../composables/useUpdater'

const toast = useToast()
const { tasks } = useTasks()
const { updateInfo, releaseUrl, installing, dialogVisible, progress, startInstallUpdate } = useUpdater()

const activeTaskCount = computed(() =>
  tasks.value.filter((t) => ['running', 'queued'].includes(t.status || '')).length,
)

const progressPercent = computed(() => {
  if (!progress.value) return 0
  if (progress.value.phase === 'pausing_tasks') return 96
  if (progress.value.phase === 'installing') return 98
  if (progress.value.phase === 'restarting') return 100
  return Math.max(0, Math.min(95, Math.round(progress.value.percent || 0)))
})

const progressLabel = computed(() => {
  if (!progress.value) return ''
  const p = progress.value
  if (p.phase === 'pausing_tasks') return '正在安全暂停运行中的下载任务并保存断点…'
  if (p.phase === 'installing') return '签名校验通过，正在写入新版本组件…'
  if (p.phase === 'restarting') return '更新完成，正在重新启动客户端…'
  const dlMb = (p.downloaded / (1024 * 1024)).toFixed(1)
  if (p.total && p.total > 0) {
    const totalMb = (p.total / (1024 * 1024)).toFixed(1)
    return `正在下载更新包：${dlMb} MB / ${totalMb} MB (${Math.round(p.percent)}%)`
  }
  return `正在下载更新包：已接收 ${dlMb} MB…`
})

async function openReleasePage() {
  try {
    await openExternalUrl(releaseUrl.value)
  } catch (error) {
    toast.error(error, '打开浏览器失败')
  }
}
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    width="min(520px, 92vw)"
    align-center
    :close-on-click-modal="!installing"
    :close-on-press-escape="!installing"
    :show-close="!installing"
    class="update-dialog"
  >
    <template #header>
      <div class="update-head">
        <div class="update-badge-icon">
          <Sparkles :size="18" />
        </div>
        <div>
          <h3>发现新版本 v{{ updateInfo?.version }}</h3>
          <p>当前版本 v{{ updateInfo?.current_version }}{{ updateInfo?.date ? ` · 发布于 ${updateInfo.date}` : '' }}</p>
        </div>
      </div>
    </template>

    <div class="update-body">
      <div v-if="updateInfo?.body" class="release-notes">
        <div class="notes-title">更新内容</div>
        <pre class="notes-content">{{ updateInfo.body }}</pre>
      </div>

      <div v-if="activeTaskCount > 0 && !installing" class="task-safe-hint">
        检测到当前有 <strong>{{ activeTaskCount }}</strong> 个任务正在运行。点击「立即更新并重启」会在下载完成后自动安全暂停任务，重启后可继续断点续传，不会丢失已下载文件。
      </div>

      <div v-if="installing" class="progress-panel">
        <div class="progress-text">{{ progressLabel }}</div>
        <el-progress :percentage="progressPercent" :stroke-width="10" :show-text="false" />
      </div>
    </div>

    <template #footer>
      <div class="update-foot">
        <el-button link size="small" @click="openReleasePage">
          <ExternalLink :size="13" style="margin-right: 4px" />浏览器手动下载
        </el-button>

        <div class="foot-right">
          <el-button :disabled="installing" @click="dialogVisible = false">稍后再说</el-button>
          <el-button type="primary" :loading="installing" @click="startInstallUpdate">
            <Download v-if="!installing" :size="15" style="margin-right: 5px" />
            {{ installing ? '正在更新…' : '立即更新并重启' }}
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.update-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.update-badge-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  background: var(--app-primary-gradient);
  color: #ffffff;
  flex: 0 0 auto;
}

.update-head h3 {
  margin: 0;
  font-size: 16.5px;
  font-weight: 700;
  color: var(--app-text);
}

.update-head p {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--app-muted);
}

.update-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.release-notes {
  border-radius: 11px;
  border: 1px solid var(--app-border);
  background: rgba(11, 16, 28, 0.68);
  padding: 12px 14px;
}

.notes-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-muted);
  margin-bottom: 6px;
}

.notes-content {
  margin: 0;
  max-height: 210px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--app-font);
  font-size: 13px;
  line-height: 1.65;
  color: var(--app-text);
}

.task-safe-hint {
  padding: 10px 13px;
  border-radius: 10px;
  border: 1px solid rgba(245, 158, 11, 0.28);
  background: rgba(245, 158, 11, 0.1);
  font-size: 12.5px;
  line-height: 1.55;
  color: #fde68a;
}

.progress-panel {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(99, 102, 241, 0.3);
  background: rgba(99, 102, 241, 0.1);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-text {
  font-size: 12.5px;
  color: #c7d2fe;
}

.update-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.foot-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
