<script setup lang="ts">
import { reactive, watch } from 'vue'
import { FolderOpened } from '@element-plus/icons-vue'
import { chooseDirectory } from '../../api/local'
import { useRuntime } from '../../composables/useRuntime'
import { useToast } from '../../composables/useToast'
import type { PublicSettings } from '../../types/settings'

const props = defineProps<{ settings: PublicSettings; saving?: boolean }>()
const emit = defineEmits<{ save: [payload: Partial<PublicSettings>] }>()
const { canUseLocal } = useRuntime()
const toast = useToast()

const form = reactive({
  output_dir: '',
  file_type: 'PDF',
  max_pages_per_combo: undefined as number | undefined,
  list_delay_seconds: 0.8,
  image_delay_seconds: 0.3,
  max_retries: 3,
  list_max_retries: 3,
  combo_failure_limit: 10,
  connect_timeout: 6,
  read_timeout: 30,
})

watch(
  () => props.settings,
  (settings) => {
    form.output_dir = String(settings.output_dir || '')
    form.file_type = String(settings.file_type || 'PDF')
    form.max_pages_per_combo = settings.max_pages_per_combo == null ? undefined : Number(settings.max_pages_per_combo)
    form.list_delay_seconds = Number(settings.list_delay_seconds || 0.8)
    form.image_delay_seconds = Number(settings.image_delay_seconds || 0.3)
    form.max_retries = Number(settings.max_retries || 3)
    form.list_max_retries = Number(settings.list_max_retries || 3)
    form.combo_failure_limit = Number(settings.combo_failure_limit ?? 10)
    form.connect_timeout = Number(settings.connect_timeout || 6)
    form.read_timeout = Number(settings.read_timeout || 30)
  },
  { immediate: true },
)

function submit() {
  const payload: Partial<PublicSettings> = { ...form }
  if (!form.output_dir.trim()) delete payload.output_dir
  else payload.output_dir = form.output_dir.trim()
  if (!form.max_pages_per_combo) payload.max_pages_per_combo = null
  emit('save', payload)
}

async function pickDirectory() {
  try {
    const result = await chooseDirectory(form.output_dir)
    if (result.path) form.output_dir = result.path
  } catch (error) {
    toast.error(error, '选择目录失败')
  }
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span>基础采集设置</span>
      </div>
    </template>

    <el-form label-position="top" class="settings-form">
      <el-form-item label="输出目录">
        <el-input v-model="form.output_dir" placeholder="留空使用默认数据目录">
          <template v-if="canUseLocal" #append>
            <el-button :icon="FolderOpened" aria-label="选择输出目录" @click="pickDirectory" />
          </template>
        </el-input>
      </el-form-item>

      <div class="settings-grid two-columns">
        <el-form-item label="文件类型">
          <el-select v-model="form.file_type" class="full-width">
            <el-option label="PDF" value="PDF" />
            <el-option label="图片" value="IMAGE" />
            <el-option label="不限" value="" />
          </el-select>
        </el-form-item>
        <el-form-item label="每个组合最多页数">
          <el-input-number v-model="form.max_pages_per_combo" :min="1" :max="999" placeholder="不限制" />
        </el-form-item>
      </div>

      <el-collapse class="settings-advanced-collapse">
        <el-collapse-item title="高级请求参数" name="request">
          <div class="settings-grid">
            <el-form-item label="列表请求间隔秒">
              <el-input-number v-model="form.list_delay_seconds" :min="0" :max="10" :step="0.1" />
            </el-form-item>
            <el-form-item label="图片请求间隔秒">
              <el-input-number v-model="form.image_delay_seconds" :min="0" :max="10" :step="0.1" />
            </el-form-item>
            <el-form-item label="底层 HTTP 重试次数">
              <el-input-number v-model="form.max_retries" :min="0" :max="20" />
              <p class="form-helper">单次接口或文件请求遇到 429/5xx 等临时错误时，由 HTTP 客户端自动重试。</p>
            </el-form-item>
            <el-form-item label="列表页最大尝试次数">
              <el-input-number v-model="form.list_max_retries" :min="1" :max="20" />
              <p class="form-helper">获取某个筛选组合的试卷列表失败时，最多尝试几次；仍失败则跳过该组合。</p>
            </el-form-item>
            <el-form-item label="连续失败组合停止数">
              <el-input-number v-model="form.combo_failure_limit" :min="0" :max="100" />
              <p class="form-helper">连续多少个筛选组合都失败后停止任务；填 0 表示不按连续失败停止。</p>
            </el-form-item>
            <el-form-item label="连接超时秒">
              <el-input-number v-model="form.connect_timeout" :min="1" :max="60" />
            </el-form-item>
            <el-form-item label="读取超时秒">
              <el-input-number v-model="form.read_timeout" :min="5" :max="300" />
            </el-form-item>
          </div>
        </el-collapse-item>
      </el-collapse>

      <el-button type="primary" :loading="saving" @click="submit">保存基础设置</el-button>
    </el-form>
  </el-card>
</template>
