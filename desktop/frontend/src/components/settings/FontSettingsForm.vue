<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ExternalLink, RefreshCw } from 'lucide-vue-next'
import { fetchFontStatus } from '../../api/fonts'
import { openExternalUrl } from '../../api/local'
import { useRuntime } from '../../composables/useRuntime'
import { useToast } from '../../composables/useToast'
import type { FontStatus } from '../../types/fonts'
import type { PublicSettings } from '../../types/settings'

const props = defineProps<{ settings?: PublicSettings; saving?: boolean }>()
const emit = defineEmits<{ save: [payload: Partial<PublicSettings>] }>()

const toast = useToast()
const { libreOfficeUrl, loadRuntime } = useRuntime()
const status = ref<FontStatus | null>(null)
const loading = ref(false)
const customSofficePath = ref('')

watch(
  () => props.settings?.soffice_path,
  (val) => {
    customSofficePath.value = String(val || '')
  },
  { immediate: true },
)

async function downloadLibreOffice() {
  try {
    await openExternalUrl(libreOfficeUrl.value)
  } catch (error) {
    toast.error(error, '打开下载链接失败')
  }
}

async function load() {
  loading.value = true
  try {
    status.value = await fetchFontStatus()
    await loadRuntime().catch(() => {})
  } catch (error) {
    toast.error(error, '读取渲染环境状态失败')
  } finally {
    loading.value = false
  }
}

function saveCustomPath() {
  emit('save', { soffice_path: customSofficePath.value.trim() })
}

onMounted(load)
</script>

<template>
  <div class="font-settings-stack">
    <el-card shadow="never">
      <template #header>
        <div class="font-header">
          <span>文档渲染与打印输出环境</span>
          <el-button size="small" :loading="loading" @click="load">
            <RefreshCw :size="13" style="margin-right: 5px" />刷新检测
          </el-button>
        </div>
      </template>

      <p class="intro-note">
        所有试卷统一采用「先渲染高清页图，再合成标准 A4 打印级 PDF」流程：10 页以内单卷优先使用官网预览图直出；PDF 与图片由内置 Pdfium 引擎直接渲染；长篇 Word 文档（.doc / .docx）自动调用本机 Office / WPS / LibreOffice 配合内置字库与系统字库完成渲染。
      </p>

      <div v-if="status" class="status-grid">
        <div class="status-tile">
          <span class="tile-label">PDF 与页图渲染核心</span>
          <div class="tile-value">
            <el-tag type="success" size="small">内置 Pdfium（已就绪）</el-tag>
          </div>
        </div>

        <div class="status-tile">
          <span class="tile-label">Word 文档渲染核心（.doc / .docx）</span>
          <div class="tile-value">
            <el-tag :type="status.libreoffice ? 'success' : 'warning'" size="small">
              {{ status.libreoffice || '未检测到本地转换核心' }}
            </el-tag>
            <el-button v-if="!status.libreoffice" type="primary" link size="small" @click="downloadLibreOffice">
              <ExternalLink :size="13" style="margin-right: 4px" />下载 LibreOffice
            </el-button>
          </div>
        </div>

        <div class="status-tile span-2">
          <span class="tile-label">内置排版与数学公式字库（离线免下载）</span>
          <div class="tile-tags">
            <el-tag type="success" size="small">系统自带中文字库（已自动挂载）</el-tag>
            <el-tag v-for="name in status.open_fonts_installed" :key="name" size="small" type="info">
              {{ name }}
            </el-tag>
          </div>
        </div>
      </div>

      <el-collapse v-if="settings !== undefined" class="settings-advanced-collapse soffice-collapse">
        <el-collapse-item title="高级：自定义 LibreOffice 可执行文件路径（可选）" name="soffice">
          <div class="soffice-row">
            <el-input
              v-model="customSofficePath"
              clearable
              placeholder="默认自动检测本机 WPS / Word / LibreOffice，便携版可手动填写 soffice 路径"
              @keyup.enter="saveCustomPath"
            />
            <el-button type="primary" :loading="saving" @click="saveCustomPath">保存路径</el-button>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>
  </div>
</template>

<style scoped>
.font-settings-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.font-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.intro-note {
  margin: 0 0 16px;
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.65;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.status-tile {
  padding: 14px 16px;
  border-radius: 10px;
  border: 1px solid var(--app-border);
  background: rgba(14, 20, 34, 0.55);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-tile.span-2 {
  grid-column: 1 / -1;
}

.tile-label {
  font-size: 12px;
  color: var(--app-muted);
}

.tile-value,
.tile-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.soffice-collapse {
  margin-top: 16px;
}

.soffice-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

@media (max-width: 760px) {
  .status-grid {
    grid-template-columns: 1fr;
  }

  .soffice-row {
    grid-template-columns: 1fr;
  }
}
</style>
