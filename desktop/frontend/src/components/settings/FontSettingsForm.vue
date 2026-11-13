<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, Download, ExternalLink, RefreshCw } from 'lucide-vue-next'
import { checkFonts, fetchFontStatus, repairFonts } from '../../api/fonts'
import { openExternalUrl } from '../../api/local'
import { useRuntime } from '../../composables/useRuntime'
import { useToast } from '../../composables/useToast'
import type { FontStatus, SampledFontEntry } from '../../types/fonts'

const toast = useToast()
const { libreOfficeUrl, loadRuntime } = useRuntime()
const status = ref<FontStatus | null>(null)
const targets = ref('')
const loading = ref(false)
const repairing = ref(false)
const showManualTest = ref(false)

const samples = '例如：Calibri, Cambria Math, 方正小标宋简体, 华文行楷'

async function downloadLibreOffice() {
  try {
    await openExternalUrl(libreOfficeUrl.value)
  } catch (error) {
    toast.error(error, '打开下载链接失败')
  }
}

const sampledRows = computed<SampledFontEntry[]>(() => status.value?.sampled_fonts || [])
const missingOpenCount = computed(() => status.value?.open_fonts_missing?.length || 0)

function sampledTagType(item: SampledFontEntry): 'success' | 'primary' | 'warning' | 'danger' {
  if (item.status === 'installed') return 'success'
  if (item.status === 'downloaded') return 'primary'
  if (item.status === 'substituted') return 'warning'
  return 'danger'
}

function sampledStatusText(item: SampledFontEntry) {
  if (item.status === 'installed') return '本机已安装'
  if (item.status === 'downloaded') return item.mapped_to ? `已自动下载 → ${item.mapped_to}` : '已自动下载'
  if (item.status === 'substituted') return item.mapped_to ? `自动替补 → ${item.mapped_to}` : '已自动替补'
  return '缺少字体'
}

const resolvedRows = computed(() => {
  const resolved = status.value?.resolved
  if (!resolved) return []
  const rows: Array<{ font: string; result: string; note: string }> = []
  for (const font of resolved.exact) {
    rows.push({ font, result: '本机已安装', note: '直接使用原字体渲染' })
  }
  const heuristicSet = new Set(resolved.heuristic || [])
  for (const [font, actual] of Object.entries(resolved.substituted || {})) {
    rows.push({
      font,
      result: `自动替补 → ${actual}`,
      note: heuristicSet.has(font)
        ? '按字形风格自动匹配本机相近中文字体或符号字体'
        : '自动匹配开源同度量替代字体',
    })
  }
  for (const font of resolved.missing) {
    rows.push({ font, result: '未找到可用字体', note: '严格模式下需手动安装对应授权字体' })
  }
  return rows
})

function targetList() {
  return targets.value
    .split(/[,，、]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    status.value = await fetchFontStatus()
    await loadRuntime().catch(() => {})
  } catch (error) {
    toast.error(error, '字体状态读取失败')
  } finally {
    loading.value = false
  }
}

async function runCheck() {
  loading.value = true
  try {
    status.value = await checkFonts(targetList())
    toast.success('检测完成')
  } catch (error) {
    toast.error(error, '检测失败')
  } finally {
    loading.value = false
  }
}

async function runRepair(customTargets?: string[]) {
  repairing.value = true
  try {
    status.value = await repairFonts(customTargets ?? [])
    const installed = status.value?.installed_now || []
    const warnings = status.value?.warnings || []
    if (installed.length) {
      toast.success(`已自动下载并安装：${installed.join('、')}`)
    } else if (warnings.length) {
      toast.info(warnings.join('；'))
    } else {
      toast.success('常用开源替代字体已全部就绪')
    }
  } catch (error) {
    toast.error(error, '下载替代字体失败')
  } finally {
    repairing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="font-settings-stack">
    <el-card shadow="never">
      <template #header>
        <div class="font-header">
          <span>文档转换与缺失字体自动处理</span>
          <div class="header-actions">
            <el-button
              v-if="missingOpenCount > 0"
              type="primary"
              size="small"
              :loading="repairing"
              @click="runRepair([])"
            >
              <Download :size="14" style="margin-right: 5px" />
              预下载常用排版与公式字体 ({{ missingOpenCount }})
            </el-button>
            <el-button size="small" :loading="loading" @click="load">
              <RefreshCw :size="13" style="margin-right: 5px" />刷新
            </el-button>
          </div>
        </div>
      </template>

      <p class="intro-note">
        下载遇到缺失西文字体或数学公式字体时会自动下载开源字体，遇到特殊中文字体（方正、华文、汉仪等）会自动采样并匹配本机相近字体；无法自动转换的文档会保留原文件并说明具体原因。
      </p>

      <div v-if="status" class="status-grid">
        <div class="status-tile">
          <span class="tile-label">文档转换核心</span>
          <div class="tile-value">
            <el-tag :type="status.libreoffice ? 'success' : 'danger'" size="small">
              {{ status.libreoffice || '未检测到 LibreOffice' }}
            </el-tag>
            <el-button v-if="!status.libreoffice" type="primary" link size="small" @click="downloadLibreOffice">
              <ExternalLink :size="13" style="margin-right: 4px" />前往下载
            </el-button>
          </div>
        </div>

        <div class="status-tile">
          <span class="tile-label">缺失字体策略</span>
          <div class="tile-value">
            <el-tag :type="status.policy === 'strict' ? 'warning' : 'success'" size="small">
              {{ status.policy === 'strict' ? '严格模式' : '自动下载 + 智能替补' }}
            </el-tag>
          </div>
        </div>

        <div class="status-tile span-2">
          <span class="tile-label">开源排版与公式字体</span>
          <div class="tile-tags">
            <el-tag v-for="name in status.open_fonts_installed" :key="name" size="small" type="success">
              {{ name }}（已就绪）
            </el-tag>
            <el-tag v-for="name in status.open_fonts_missing" :key="`m-${name}`" size="small" type="info">
              {{ name }}（按需自动下载）
            </el-tag>
          </div>
        </div>

        <div class="status-tile span-2">
          <span class="tile-label">字体缓存目录</span>
          <span class="mono tile-path">{{ status.install_dir }}</span>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="font-header">
          <span>试卷字体自动采样记录 ({{ sampledRows.length }})</span>
          <span class="muted-hint">下载转换试卷时自动采集</span>
        </div>
      </template>

      <el-table v-if="sampledRows.length" :data="sampledRows" size="small" max-height="300">
        <el-table-column prop="font" label="试卷声明字体" min-width="180" />
        <el-table-column prop="seen_count" label="采样次数" width="100" />
        <el-table-column label="自动处理结果" min-width="220">
          <template #default="{ row }">
            <el-tag :type="sampledTagType(row)" size="small">
              {{ sampledStatusText(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="最近遇到时间" width="170" />
      </el-table>
      <div v-else class="empty-sampled">
        暂无采样记录。开始下载任务后，系统会自动记录试卷用到的字体及自动替补方案。
      </div>
    </el-card>

    <!-- 清爽暗色折叠诊断面板 -->
    <div class="manual-diag-box" :class="{ open: showManualTest }">
      <button type="button" class="manual-diag-trigger" @click="showManualTest = !showManualTest">
        <div class="trigger-text">
          <strong>字体匹配测试工具（可选）</strong>
          <span>输入任意字体名称，查看本机如何自动匹配或替补</span>
        </div>
        <ChevronDown :size="16" class="trigger-chevron" :class="{ rotated: showManualTest }" />
      </button>

      <div v-if="showManualTest" class="manual-diag-body">
        <div class="manual-input-row">
          <el-input
            v-model="targets"
            :placeholder="samples"
            clearable
            class="manual-input"
            @keyup.enter="runCheck"
          />
          <el-button :loading="loading" @click="runCheck">测试匹配</el-button>
          <el-button type="primary" plain :loading="repairing" @click="runRepair(targetList())">
            补齐开源字体
          </el-button>
        </div>

        <el-table v-if="resolvedRows.length" :data="resolvedRows" size="small" class="font-table">
          <el-table-column prop="font" label="声明字体" width="200" />
          <el-table-column prop="result" label="处理方案" width="230" />
          <el-table-column prop="note" label="说明" />
        </el-table>
      </div>
    </div>
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

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.intro-note {
  margin: 0 0 14px;
  padding: 11px 14px;
  border-radius: 10px;
  border: 1px solid rgba(16, 185, 129, 0.25);
  background: rgba(16, 185, 129, 0.08);
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.6;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.status-tile {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--app-border);
  background: rgba(11, 16, 28, 0.55);
}

.status-tile.span-2 {
  grid-column: span 2;
}

.tile-label {
  font-size: 12px;
  color: var(--app-muted);
}

.tile-value {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tile-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tile-path {
  font-size: 12px;
  color: var(--app-text);
  word-break: break-all;
}

.muted-hint {
  font-size: 12px;
  color: var(--app-muted);
}

.empty-sampled {
  padding: 18px 8px;
  font-size: 13px;
  color: var(--app-muted);
  text-align: center;
}

.manual-diag-box {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  background: var(--app-surface);
  overflow: hidden;
  transition: border-color 160ms ease;
}

.manual-diag-box.open {
  border-color: var(--app-border-strong);
}

.manual-diag-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  border: none;
  background: transparent;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
  transition: background-color 150ms ease;
}

.manual-diag-trigger:hover {
  background: rgba(30, 42, 68, 0.35);
}

.trigger-text {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.trigger-text strong {
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text);
}

.trigger-text span {
  font-size: 12.5px;
  color: var(--app-muted);
}

.trigger-chevron {
  color: var(--app-muted);
  flex: 0 0 auto;
  transition: transform 180ms ease;
}

.trigger-chevron.rotated {
  transform: rotate(180deg);
}

.manual-diag-body {
  padding: 16px 20px 18px;
  border-top: 1px solid var(--app-border);
}

.manual-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.manual-input {
  flex: 1 1 auto;
}

.font-table {
  margin-top: 14px;
}

@media (max-width: 720px) {
  .status-grid {
    grid-template-columns: 1fr;
  }
  .status-tile.span-2 {
    grid-column: span 1;
  }
  .manual-input-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
