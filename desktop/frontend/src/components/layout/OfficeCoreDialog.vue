<script setup lang="ts">
import { computed, ref } from 'vue'
import { Copy, ExternalLink, FolderOpen, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import { chooseFile, openExternalUrl } from '../../api/local'
import { updateSettings } from '../../api/settings'
import { useRuntime } from '../../composables/useRuntime'
import { useToast } from '../../composables/useToast'

const DOWNLOAD_URL = 'https://www.libreoffice.org/download/'

const toast = useToast()
const { runtime, hasOfficeCore, libreOfficeUrl, loadRuntime } = useRuntime()

const checking = ref(false)
const showCustomPath = ref(false)
const customSofficePath = ref('')
const savingPath = ref(false)

const visible = computed(() => Boolean(runtime.value && !hasOfficeCore.value))
const targetUrl = computed(() => libreOfficeUrl.value || DOWNLOAD_URL)

async function openDownloadPage() {
  try {
    await openExternalUrl(targetUrl.value)
  } catch (error) {
    toast.error(error, '打开下载页面失败，请手动复制链接访问')
  }
}

async function copyDownloadUrl() {
  try {
    await navigator.clipboard.writeText(targetUrl.value)
    toast.success('下载链接已复制')
  } catch {
    toast.error('复制失败，请手动选中复制链接')
  }
}

async function recheckCore() {
  checking.value = true
  try {
    await loadRuntime()
    if (hasOfficeCore.value) {
      toast.success('已检测到文档转换核心')
    } else {
      toast.error('仍未检测到 LibreOffice，请确认已完成安装')
    }
  } catch (error) {
    toast.error(error, '检测失败')
  } finally {
    checking.value = false
  }
}

async function pickSofficeFile() {
  try {
    const res = await chooseFile('选择 LibreOffice soffice 程序', customSofficePath.value)
    if (res.path) {
      customSofficePath.value = res.path
    }
  } catch (error) {
    toast.error(error, '选择文件失败')
  }
}

async function saveCustomPath() {
  const path = customSofficePath.value.trim()
  if (!path) return
  savingPath.value = true
  try {
    await updateSettings({ soffice_path: path })
    await loadRuntime()
    if (hasOfficeCore.value) {
      toast.success('转换核心路径已生效')
    } else {
      toast.error('指定路径未能识别为有效的 soffice 程序，请检查路径')
    }
  } catch (error) {
    toast.error(error, '保存路径失败')
  } finally {
    savingPath.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    width="min(560px, 94vw)"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    align-center
    class="office-core-dialog"
  >
    <template #header>
      <div class="core-dialog-title">
        <span class="core-warning-badge">
          <TriangleAlert :size="18" />
        </span>
        <div>
          <h3>需要安装文档转换核心</h3>
          <p>未检测到 LibreOffice，Word 与复合压缩包试卷将无法转为 PDF</p>
        </div>
      </div>
    </template>

    <div class="core-dialog-body">
      <div class="core-steps">
        <div class="core-step-item">
          <span class="step-num">1</span>
          <div>
            <strong>前往官网下载并安装 LibreOffice（免费开源）</strong>
            <p>macOS 下载后将 LibreOffice.app 拖入「应用程序」目录；Windows 按默认向导完成安装即可。</p>
          </div>
        </div>
        <div class="core-step-item">
          <span class="step-num">2</span>
          <div>
            <strong>安装完成后点击下方「我已安装，重新检测」</strong>
            <p>无需重启软件，检测通过后窗口会自动关闭。</p>
          </div>
        </div>
      </div>

      <div class="core-url-box">
        <span class="mono">{{ targetUrl }}</span>
        <el-button size="small" text @click="copyDownloadUrl">
          <Copy :size="13" style="margin-right: 4px" />复制链接
        </el-button>
      </div>

      <div class="core-custom-toggle">
        <button type="button" class="link-btn" @click="showCustomPath = !showCustomPath">
          {{ showCustomPath ? '收起手动路径设置' : '已安装在自定义目录？手动指定 soffice 路径' }}
        </button>
        <div v-if="showCustomPath" class="core-custom-form">
          <el-input
            v-model="customSofficePath"
            placeholder="例如：/Applications/LibreOffice.app/Contents/MacOS/soffice 或 C:\Program Files\LibreOffice\program\soffice.exe"
          >
            <template #append>
              <el-button @click="pickSofficeFile">
                <FolderOpen :size="14" />
              </el-button>
            </template>
          </el-input>
          <el-button :loading="savingPath" :disabled="!customSofficePath.trim()" @click="saveCustomPath">
            保存并验证
          </el-button>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="core-dialog-footer">
        <el-button size="large" :loading="checking" @click="recheckCore">
          <RefreshCw :size="15" style="margin-right: 6px" />我已安装，重新检测
        </el-button>
        <el-button type="primary" size="large" @click="openDownloadPage">
          <ExternalLink :size="15" style="margin-right: 6px" />前往下载 LibreOffice
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.core-dialog-title {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.core-warning-badge {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  color: var(--app-warning);
  background: rgba(245, 158, 11, 0.14);
  border: 1px solid rgba(245, 158, 11, 0.32);
}

.core-dialog-title h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--app-text);
}

.core-dialog-title p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--app-muted);
}

.core-dialog-body {
  display: grid;
  gap: 14px;
}

.core-steps {
  display: grid;
  gap: 12px;
  padding: 14px;
  border-radius: 11px;
  background: rgba(15, 23, 42, 0.65);
  border: 1px solid var(--app-border);
}

.core-step-item {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.step-num {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  color: #c7d2fe;
  background: rgba(99, 102, 241, 0.22);
  border: 1px solid rgba(129, 140, 248, 0.34);
}

.core-step-item strong {
  display: block;
  font-size: 13.5px;
  color: var(--app-text);
}

.core-step-item p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--app-muted);
}

.core-url-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 9px;
  background: rgba(9, 13, 22, 0.8);
  border: 1px solid var(--app-border);
  font-size: 12.5px;
  color: #a5b4fc;
}

.core-url-box span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-custom-toggle {
  display: grid;
  gap: 8px;
}

.link-btn {
  justify-self: start;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--app-muted);
  font-size: 12.5px;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.link-btn:hover {
  color: var(--app-text);
}

.core-custom-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.core-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
</style>
