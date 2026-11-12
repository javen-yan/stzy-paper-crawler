<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { checkFonts, fetchFontStatus, repairFonts } from '../../api/fonts'
import { useToast } from '../../composables/useToast'
import type { FontStatus } from '../../types/fonts'

const toast = useToast()
const status = ref<FontStatus | null>(null)
const targets = ref('')
const loading = ref(false)
const repairing = ref(false)

const samples = 'Calibri, Cambria, Times New Roman, 宋体'

const resolvedRows = computed(() => {
  const resolved = status.value?.resolved
  if (!resolved) return []
  const rows: Array<{ font: string; result: string; note: string }> = []
  for (const font of resolved.exact) {
    rows.push({ font, result: '原版已安装', note: '与原文声明一致' })
  }
  for (const [font, actual] of Object.entries(resolved.substituted || {})) {
    rows.push({
      font,
      result: `替代 → ${actual}`,
      note: resolved.visual_review ? '中文字体替代会改变行高，仍需页数与文字覆盖校验' : '度量一致，分页不受影响',
    })
  }
  for (const font of resolved.missing) {
    rows.push({ font, result: '缺失', note: '请安装有授权的字体，或设置 STZY_WORD_FONT_DIR 指向字体目录' })
  }
  return rows
})

function targetList() {
  return targets.value
    .split(/[,，、\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    status.value = await fetchFontStatus()
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
    toast.success('自检完成')
  } catch (error) {
    toast.error(error, '自检失败')
  } finally {
    loading.value = false
  }
}

async function runRepair() {
  repairing.value = true
  try {
    status.value = await repairFonts(targetList())
    const installed = status.value?.installed_now || []
    const warnings = status.value?.warnings || []
    if (warnings.length) {
      toast.error(warnings.join('；'), '部分字体未补齐')
    } else if (installed.length) {
      toast.success(`已安装 ${installed.join('、')}`)
    } else {
      toast.success('无需下载，字体目录已就绪')
    }
  } catch (error) {
    toast.error(error, '补齐失败')
  } finally {
    repairing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <el-card shadow="never">
      <template #header>
        <div class="font-header">
          <span>Word 字体自检</span>
          <el-button size="small" :loading="loading" @click="load">刷新状态</el-button>
        </div>
      </template>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="缺字体时先找本机已授权的原版字体，再下载开源且度量一致的替代（Calibri→Carlito、Cambria→Caladea、Times New Roman→Tinos）。拉丁替代不改变分页；中文字体只能替代为系统同名字体或开源宋体，行高会变，页数按实际结果发布并在报告里标记待视觉核对。"
      />
      <el-descriptions v-if="status" :column="2" border class="font-status">
        <el-descriptions-item label="fontconfig">
          <el-tag :type="status.font_config ? 'success' : 'danger'" size="small">
            {{ status.font_config ? '已安装' : '缺失' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="LibreOffice">
          <el-tag :type="status.libreoffice ? 'success' : 'danger'" size="small">
            {{ status.libreoffice || '未找到 soffice' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="缺字体策略">
          <el-tag :type="status.policy === 'strict' ? 'warning' : 'success'" size="small">
            {{ status.policy === 'strict' ? '严格：只接受原版字体' : '替代：接受度量一致的开源字体' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="自动下载开源替代">
          <el-tag :type="status.auto_install ? 'success' : 'info'" size="small">
            {{ status.auto_install ? '已开启' : '已关闭' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="字体安装目录" :span="2">
          <span class="mono">{{ status.install_dir }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="生效的字体目录" :span="2">
          <div v-for="dir in status.directories" :key="dir" class="mono">{{ dir }}</div>
        </el-descriptions-item>
        <el-descriptions-item label="已就绪的开源替代" :span="2">
          <el-tag v-for="name in status.open_fonts_installed" :key="name" size="small" class="tag">{{ name }}</el-tag>
          <span v-if="!status.open_fonts_installed.length" class="muted">无</span>
        </el-descriptions-item>
        <el-descriptions-item label="可下载的开源替代" :span="2">
          <el-tag v-for="name in status.open_fonts_missing" :key="name" size="small" type="info" class="tag">{{ name }}</el-tag>
          <span v-if="!status.open_fonts_missing.length" class="muted">全部已就绪</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>按字体名自检</template>
      <el-form label-position="top">
        <el-form-item label="字体名（逗号分隔，可留空检查全部）">
          <el-input v-model="targets" :placeholder="samples" clearable />
        </el-form-item>
        <div class="actions">
          <el-button :loading="loading" @click="runCheck">自检</el-button>
          <el-button type="primary" :loading="repairing" @click="runRepair">一键补齐</el-button>
        </div>
      </el-form>

      <el-alert
        v-for="warning in status?.warnings || []"
        :key="warning"
        :title="warning"
        type="warning"
        show-icon
        :closable="false"
        class="font-warning"
      />

      <el-table v-if="resolvedRows.length" :data="resolvedRows" size="small" class="font-table">
        <el-table-column prop="font" label="声明字体" width="220" />
        <el-table-column prop="result" label="结果" width="260" />
        <el-table-column prop="note" label="说明" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.font-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.font-status {
  margin-top: 12px;
}
.tag {
  margin: 0 6px 6px 0;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  word-break: break-all;
}
.muted {
  color: var(--el-text-color-secondary);
}
.actions {
  display: flex;
  gap: 8px;
}
.font-warning {
  margin-top: 12px;
}
.font-table {
  margin-top: 12px;
}
</style>
