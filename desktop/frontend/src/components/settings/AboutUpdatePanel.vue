<script setup lang="ts">
import { Download, ExternalLink, RefreshCw, ShieldCheck } from 'lucide-vue-next'
import { openExternalUrl } from '../../api/local'
import { useToast } from '../../composables/useToast'
import { useUpdater } from '../../composables/useUpdater'

const toast = useToast()
const {
  updateInfo,
  currentVersion,
  hasUpdate,
  releaseUrl,
  checking,
  checkError,
  checkForUpdates,
  openUpdateDialog,
} = useUpdater()

async function openReleasePage() {
  try {
    await openExternalUrl(releaseUrl.value)
  } catch (error) {
    toast.error(error, '打开网页失败')
  }
}
</script>

<template>
  <div class="about-stack">
    <el-card shadow="never">
      <div class="version-banner">
        <div class="version-info">
          <div class="version-title">
            <strong>试卷下载器</strong>
            <span class="ver-pill mono">v{{ currentVersion }}</span>
            <el-tag v-if="hasUpdate" type="warning" size="small">发现新版本 v{{ updateInfo?.version }}</el-tag>
            <el-tag v-else-if="updateInfo && !hasUpdate" type="success" size="small">已是最新版本</el-tag>
          </div>
          <p class="version-desc">
            支持应用内签名校验自动更新（Minisign 防篡改校验 + 国内加速镜像与 GitHub 官方双源回退）。
          </p>
        </div>

        <div class="version-actions">
          <el-button v-if="hasUpdate" type="primary" @click="openUpdateDialog">
            <Download :size="14" style="margin-right: 5px" />立即更新到 v{{ updateInfo?.version }}
          </el-button>
          <el-button :loading="checking" @click="checkForUpdates({ silent: false, openIfAvailable: true })">
            <RefreshCw v-if="!checking" :size="14" style="margin-right: 5px" />检查更新
          </el-button>
          <el-button @click="openReleasePage">
            <ExternalLink :size="14" style="margin-right: 5px" />GitHub 发布页
          </el-button>
        </div>
      </div>

      <div v-if="checkError" class="error-strip">
        最近一次在线检查失败：{{ checkError }}（您仍可直接点击「GitHub 发布页」手动下载最新安装包）
      </div>

      <div class="update-notes-grid">
        <div class="note-card">
          <ShieldCheck :size="17" class="note-icon" />
          <div>
            <strong>更新不会丢失数据与任务</strong>
            <p>所有账号凭据、系统配置、断点记录及已下载的试卷目录均独立存储，升级后完整保留。</p>
          </div>
        </div>
        <div class="note-card">
          <Download :size="17" class="note-icon" />
          <div>
            <strong>macOS 免二次隔离验证</strong>
            <p>通过应用内在线更新直接覆盖升级后，不会触发浏览器下载的“文件已损坏”拦截提示。</p>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.about-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.version-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--app-border);
}

.version-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.version-title strong {
  font-size: 16px;
  color: var(--app-text);
}

.ver-pill {
  padding: 2px 9px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.18);
  border: 1px solid rgba(129, 140, 248, 0.35);
  color: #c7d2fe;
  font-size: 12px;
}

.version-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--app-muted);
}

.version-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.error-strip {
  margin-top: 14px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(245, 158, 11, 0.28);
  background: rgba(245, 158, 11, 0.1);
  color: #fde68a;
  font-size: 12.5px;
}

.update-notes-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.note-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 13px 15px;
  border-radius: 11px;
  border: 1px solid var(--app-border);
  background: rgba(11, 16, 28, 0.55);
}

.note-icon {
  color: #818cf8;
  flex: 0 0 auto;
  margin-top: 2px;
}

.note-card strong {
  display: block;
  font-size: 13.5px;
  color: var(--app-text);
}

.note-card p {
  margin: 4px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--app-muted);
}

@media (max-width: 720px) {
  .update-notes-grid {
    grid-template-columns: 1fr;
  }
}
</style>
