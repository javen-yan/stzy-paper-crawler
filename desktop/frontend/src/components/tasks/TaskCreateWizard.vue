<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Calculator, ChevronDown, Download, Plus, RefreshCw, RotateCcw, UserRoundCog } from 'lucide-vue-next'
import { fetchCatalogs, refreshCatalogs } from '../../api/catalogs'
import { useTasks } from '../../composables/useTasks'
import { useToast } from '../../composables/useToast'
import type { Account } from '../../types/accounts'
import type { CatalogState } from '../../types/catalogs'
import type { TaskCreateForm, TaskEstimateResult } from '../../types/tasks'

const props = defineProps<{ accounts: Account[]; submitting?: boolean }>()
const emit = defineEmits<{ submit: [form: TaskCreateForm] }>()
const router = useRouter()
const toast = useToast()
const { estimateTask } = useTasks()

const visible = ref(false)
const showMoreOptions = ref(false)
const catalog = ref<CatalogState | null>(null)
const catalogLoading = ref(false)
const catalogSyncing = ref(false)
const catalogError = ref('')
const estimateLoading = ref(false)
const estimateResult = ref<TaskEstimateResult | null>(null)
const estimatedSignature = ref('')

const form = reactive<TaskCreateForm>({
  title: '',
  mode: 'crawl',
  studyPhase: '300',
  fileType: '',
  downloadPaid: false,
  maxPagesPerCombo: undefined,
  subjectLabels: {},
  filterLabels: {},
  subjects: [],
  scenes: [],
  grades: [],
  terms: [],
  provinces: [],
  years: [],
  ranks: [],
})

const usableAccounts = computed(() => props.accounts.filter((account) => account.usable && account.enabled))
const canSubmit = computed(() => usableAccounts.value.length > 0)

const studyPhaseOptions = computed(() => {
  const phases = catalog.value?.study_phases
  if (phases && typeof phases === 'object' && Object.keys(phases).length) {
    return Object.entries(phases).map(([value, label]) => ({ value, label: String(label) }))
  }
  return [
    { value: '300', label: '高中' },
    { value: '200', label: '初中' },
  ]
})

const subjectOptions = computed(() => {
  const subjects = catalog.value?.subjects as Record<string, Record<string, string>> | undefined
  const current = subjects?.[form.studyPhase] || {}
  return Object.entries(current).map(([value, label]) => ({ value, label }))
})

function tagOptions(field: string, phase = form.studyPhase) {
  const catalogs = catalog.value?.catalogs as Record<string, Record<string, Array<{ code: string; name: string }>>> | undefined
  const items = catalogs?.[phase]?.[field] || []
  return items.map((item) => ({ value: item.code, label: item.name }))
}

const yearOptions = computed(() => tagOptions('yearCode'))
const sceneOptions = computed(() => tagOptions('sceneCode'))
const gradeOptions = computed(() => tagOptions('gradeCode'))
const termOptions = computed(() => tagOptions('termCode'))
const rankOptions = computed(() => tagOptions('rank'))
const provinceOptions = computed(() => tagOptions('provinceCode'))

const isCatalogPopulated = computed(() => {
  return subjectOptions.value.length > 0 && (yearOptions.value.length > 0 || provinceOptions.value.length > 0)
})

function labelsFor(options: Array<{ value: string; label: string }>, selected: string[]) {
  const map = new Map(options.map((o) => [o.value, o.label]))
  return selected.map((code) => map.get(code) || '').filter(Boolean)
}

const phaseLabel = computed(() => studyPhaseOptions.value.find((p) => p.value === form.studyPhase)?.label || '高中')

const autoTitlePlaceholder = computed(() => {
  const parts = [
    phaseLabel.value,
    ...labelsFor(subjectOptions.value, form.subjects).slice(0, 2),
    ...labelsFor(provinceOptions.value, form.provinces).slice(0, 2),
    ...labelsFor(yearOptions.value, form.years).slice(0, 1),
    ...labelsFor(sceneOptions.value, form.scenes).slice(0, 1),
  ].filter(Boolean)
  return parts.length > 1 ? `留空自动命名为：${parts.join(' · ')}` : '可选，留空自动按所选条件生成任务名'
})

const hasNarrowingFilter = computed(() => {
  return Boolean(
    form.subjects.length ||
      form.provinces.length ||
      form.years.length ||
      form.scenes.length ||
      form.grades.length ||
      form.terms.length ||
      form.ranks.length,
  )
})

const hasExtraOptionsSelected = computed(() => Boolean(form.ranks.length || form.fileType || form.maxPagesPerCombo))

const estimateStats = computed(() => estimateResult.value?.stats || {})
const estimatedResources = computed(() => numberStat(estimateStats.value.resources_seen))
const estimatedCombos = computed(() => numberStat(estimateStats.value.total_combos || estimateStats.value.completed_combos))
const isEstimateFresh = computed(() => Boolean(estimateResult.value && estimatedSignature.value === currentFilterSignature()))

function numberStat(value: unknown) {
  const numeric = Number(value || 0)
  return Number.isFinite(numeric) ? numeric : 0
}

function hasAnyCatalogData(data: CatalogState | null | undefined) {
  if (!data) return false
  const subjects = data.subjects as Record<string, Record<string, string>> | undefined
  const catalogs = data.catalogs as Record<string, Record<string, unknown[]>> | undefined
  const hasSubj = Boolean(subjects && Object.values(subjects).some((group) => group && Object.keys(group).length > 0))
  const hasTags = Boolean(
    catalogs &&
      Object.values(catalogs).some(
        (phaseMap) => phaseMap && Object.values(phaseMap).some((arr) => Array.isArray(arr) && arr.length > 0),
      ),
  )
  return hasSubj && hasTags
}

function resetFilters(keepPhase = false) {
  if (!keepPhase) {
    form.studyPhase = '300'
    form.title = ''
    form.fileType = ''
    form.maxPagesPerCombo = undefined
  }
  form.subjects = []
  form.scenes = []
  form.grades = []
  form.terms = []
  form.provinces = []
  form.years = []
  form.ranks = []
  estimateResult.value = null
  estimatedSignature.value = ''
}

function handlePhaseChange(value: string) {
  if (form.studyPhase === value) return
  form.studyPhase = value
  resetFilters(true)
}

function syncLabelsIntoForm() {
  const subjMap = new Map(subjectOptions.value.map((o) => [o.value, o.label]))
  form.subjectLabels = Object.fromEntries(
    form.subjects.map((code) => [code, subjMap.get(code) || '']).filter(([, label]) => Boolean(label)),
  )
  form.filterLabels = {
    scenes: labelsFor(sceneOptions.value, form.scenes),
    grades: labelsFor(gradeOptions.value, form.grades),
    terms: labelsFor(termOptions.value, form.terms),
    provinces: labelsFor(provinceOptions.value, form.provinces),
    years: labelsFor(yearOptions.value, form.years),
    ranks: labelsFor(rankOptions.value, form.ranks),
  }
}

function currentFilterSignature() {
  return JSON.stringify({
    studyPhase: form.studyPhase,
    fileType: form.fileType,
    maxPagesPerCombo: form.maxPagesPerCombo || null,
    subjects: [...form.subjects].sort(),
    scenes: [...form.scenes].sort(),
    grades: [...form.grades].sort(),
    terms: [...form.terms].sort(),
    provinces: [...form.provinces].sort(),
    years: [...form.years].sort(),
    ranks: [...form.ranks].sort(),
  })
}

async function ensureCatalogsLoaded(forceRefresh = false) {
  catalogError.value = ''
  if (!forceRefresh) {
    catalogLoading.value = true
    try {
      const cached = await fetchCatalogs()
      catalog.value = cached
      if (hasAnyCatalogData(cached)) {
        return
      }
    } catch (error) {
      catalogError.value = error instanceof Error ? error.message : String(error)
    } finally {
      catalogLoading.value = false
    }
  }

  if (!canSubmit.value && !forceRefresh) {
    return
  }

  catalogSyncing.value = true
  try {
    catalog.value = await refreshCatalogs()
    if (forceRefresh) {
      toast.success('筛选分类已同步')
    }
  } catch (error) {
    catalogError.value = error instanceof Error ? error.message : String(error)
    if (forceRefresh) {
      toast.error(error, '分类同步失败')
    }
  } finally {
    catalogSyncing.value = false
  }
}

watch(
  () => [visible.value, canSubmit.value] as const,
  ([isOpen, hasAccount]) => {
    if (isOpen && hasAccount && !hasAnyCatalogData(catalog.value) && !catalogSyncing.value && !catalogLoading.value) {
      ensureCatalogsLoaded(true)
    }
  },
)

function openDialog() {
  resetFilters(false)
  showMoreOptions.value = false
  visible.value = true
  ensureCatalogsLoaded(false)
}

async function runEstimate() {
  if (!canSubmit.value) return
  syncLabelsIntoForm()
  estimateLoading.value = true
  try {
    estimateResult.value = await estimateTask({ ...form, mode: 'estimate' })
    estimatedSignature.value = currentFilterSignature()
    toast.success(`预估完成：约 ${numberStat(estimateResult.value?.stats?.resources_seen)} 份试卷`)
  } catch (error) {
    toast.error(error, '预估失败')
  } finally {
    estimateLoading.value = false
  }
}

async function submitDownload() {
  if (!canSubmit.value) return
  if (!isEstimateFresh.value && !hasNarrowingFilter.value) {
    try {
      await ElMessageBox.confirm(
        '当前未选择学科、年份或地区，直接开始会扫描当前学段全部试卷。建议至少选择学科或年份后再下载，确定继续吗？',
        '范围确认',
        {
          confirmButtonText: '继续下载',
          cancelButtonText: '返回选择',
          type: 'warning',
        },
      )
    } catch {
      return
    }
  }
  syncLabelsIntoForm()
  visible.value = false
  emit('submit', { ...form, mode: 'crawl' })
}

function goAccounts() {
  visible.value = false
  router.push('/accounts')
}
</script>

<template>
  <el-button type="primary" size="large" :icon="Plus" @click="openDialog">新建下载任务</el-button>

  <el-dialog
    v-model="visible"
    width="min(660px, 94vw)"
    align-center
    destroy-on-close
    class="task-create-dialog"
  >
    <template #header>
      <div class="dialog-head">
        <div>
          <h3>新建下载任务</h3>
          <p>支持多选与搜索过滤，留空代表不限该项</p>
        </div>
        <div class="dialog-head-right">
          <span class="account-pill" :class="{ warn: !canSubmit }">
            {{ canSubmit ? `可用账号 ${usableAccounts.length}` : '无可用账号' }}
          </span>
          <el-button
            size="small"
            :loading="catalogSyncing"
            :disabled="!canSubmit"
            title="从官网重新拉取最新分类"
            @click="ensureCatalogsLoaded(true)"
          >
            <RefreshCw v-if="!catalogSyncing" :size="13" style="margin-right: 4px" />同步分类
          </el-button>
        </div>
      </div>
    </template>

    <div class="dialog-body">
      <!-- 未配置账号引导 -->
      <div v-if="!canSubmit" class="state-banner warn">
        <div>
          <strong>请先添加至少一个可用账号</strong>
          <p>拉取筛选分类、预估试卷数和下载文件均需要登录账号。</p>
        </div>
        <el-button type="primary" :icon="UserRoundCog" @click="goAccounts">去添加账号</el-button>
      </div>

      <!-- 首次自动同步分类加载态 -->
      <div v-else-if="(catalogLoading || catalogSyncing) && !isCatalogPopulated" class="sync-loading-box">
        <el-skeleton :rows="4" animated />
        <p>正在同步学科、年份与地区分类，请稍候…</p>
      </div>

      <!-- 同步失败引导 -->
      <div v-else-if="!isCatalogPopulated" class="state-banner error">
        <div>
          <strong>尚未获取到筛选分类</strong>
          <p>{{ catalogError || '网络波动或账号状态过期，请点击重新同步。' }}</p>
        </div>
        <el-button type="primary" :loading="catalogSyncing" @click="ensureCatalogsLoaded(true)">
          重新同步
        </el-button>
      </div>

      <!-- 清爽双列下拉表单 -->
      <div v-if="isCatalogPopulated || canSubmit" class="compact-form" :class="{ disabled: !isCatalogPopulated }">
        <!-- 学段分段切换 + 重置 -->
        <div class="phase-bar">
          <div class="phase-segmented">
            <button
              v-for="phase in studyPhaseOptions"
              :key="phase.value"
              type="button"
              class="seg-btn"
              :class="{ active: form.studyPhase === phase.value }"
              @click="handlePhaseChange(phase.value)"
            >
              {{ phase.label }}
            </button>
          </div>

          <el-button
            v-if="hasNarrowingFilter || hasExtraOptionsSelected"
            link
            size="small"
            @click="resetFilters(true)"
          >
            <RotateCcw :size="12" style="margin-right: 4px" />清空已选条件
          </el-button>
        </div>

        <!-- 2x3 核心条件网格 -->
        <div class="form-grid-2">
          <div class="field-item">
            <label>学科</label>
            <el-select
              v-model="form.subjects"
              multiple
              filterable
              clearable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              placeholder="全部学科"
            >
              <el-option v-for="item in subjectOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </div>

          <div class="field-item">
            <label>年份</label>
            <el-select
              v-model="form.years"
              multiple
              filterable
              clearable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              placeholder="不限年份"
            >
              <el-option v-for="item in yearOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </div>

          <div class="field-item">
            <label>地区</label>
            <el-select
              v-model="form.provinces"
              multiple
              filterable
              clearable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              placeholder="全部地区（可输入省份搜索）"
            >
              <el-option v-for="item in provinceOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </div>

          <div class="field-item">
            <label>考试类型</label>
            <el-select
              v-model="form.scenes"
              multiple
              filterable
              clearable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              placeholder="不限类型"
            >
              <el-option v-for="item in sceneOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </div>

          <div class="field-item">
            <label>年级</label>
            <el-select
              v-model="form.grades"
              multiple
              clearable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              placeholder="不限年级"
            >
              <el-option v-for="item in gradeOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </div>

          <div class="field-item">
            <label>学期</label>
            <el-select
              v-model="form.terms"
              multiple
              clearable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              placeholder="不限学期"
            >
              <el-option v-for="item in termOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </div>
        </div>

        <!-- 任务名称 -->
        <div class="field-item">
          <label>任务名称（可选）</label>
          <el-input v-model="form.title" :placeholder="autoTitlePlaceholder" clearable />
        </div>

        <!-- 折叠更多限制 -->
        <div class="extra-panel" :class="{ open: showMoreOptions }">
          <button type="button" class="extra-trigger" @click="showMoreOptions = !showMoreOptions">
            <span>
              更多限制（试卷等级 / 文件格式 / 页数上限）
              <em v-if="hasExtraOptionsSelected" class="extra-dot">已设置</em>
            </span>
            <ChevronDown :size="15" class="extra-chevron" :class="{ rotated: showMoreOptions }" />
          </button>

          <div v-if="showMoreOptions" class="extra-body">
            <div class="form-grid-3">
              <div class="field-item">
                <label>试卷等级</label>
                <el-select
                  v-model="form.ranks"
                  multiple
                  clearable
                  collapse-tags
                  :max-collapse-tags="1"
                  placeholder="不限等级"
                >
                  <el-option v-for="item in rankOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
              </div>

              <div class="field-item">
                <label>文件格式</label>
                <el-select v-model="form.fileType" placeholder="全部格式">
                  <el-option label="全部格式（推荐）" value="" />
                  <el-option label="仅 PDF" value="PDF" />
                  <el-option label="仅图片" value="IMAGE" />
                </el-select>
              </div>

              <div class="field-item">
                <label>单组合最大页数</label>
                <el-input-number
                  v-model="form.maxPagesPerCombo"
                  :min="1"
                  :max="999"
                  controls-position="right"
                  placeholder="默认"
                  class="full-width-num"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="dialog-foot">
        <div class="foot-left">
          <div v-if="estimateResult" class="estimate-pill" :class="{ stale: !isEstimateFresh }">
            <template v-if="isEstimateFresh">
              预计匹配 <strong class="mono">{{ estimatedResources }}</strong> 份试卷（{{ estimatedCombos }} 组）
            </template>
            <template v-else>条件已变更，可重新预估</template>
          </div>
        </div>

        <div class="foot-actions">
          <el-button @click="visible = false">取消</el-button>
          <el-button
            :loading="estimateLoading"
            :disabled="!canSubmit || !isCatalogPopulated"
            @click="runEstimate"
          >
            <Calculator v-if="!estimateLoading" :size="15" style="margin-right: 5px" />预估数量
          </el-button>
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!canSubmit || !isCatalogPopulated"
            @click="submitDownload"
          >
            <Download v-if="!submitting" :size="15" style="margin-right: 5px" />
            {{ isEstimateFresh ? `开始下载（约 ${estimatedResources} 份）` : '开始下载' }}
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-right: 22px;
  flex-wrap: wrap;
}

.dialog-head h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--app-text);
}

.dialog-head p {
  margin: 3px 0 0;
  font-size: 12.5px;
  color: var(--app-muted);
}

.dialog-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.account-pill {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  background: rgba(16, 185, 129, 0.13);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #6ee7b7;
}

.account-pill.warn {
  background: rgba(245, 158, 11, 0.14);
  border-color: rgba(245, 158, 11, 0.34);
  color: #fcd34d;
}

.dialog-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.state-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 16px;
  border-radius: 12px;
}

.state-banner.warn {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.28);
}

.state-banner.error {
  background: rgba(244, 63, 94, 0.1);
  border: 1px solid rgba(244, 63, 94, 0.28);
}

.state-banner strong {
  display: block;
  font-size: 13.5px;
  color: var(--app-text);
}

.state-banner p {
  margin: 3px 0 0;
  font-size: 12.5px;
  color: var(--app-muted);
}

.sync-loading-box {
  padding: 16px;
  border-radius: 12px;
  border: 1px solid var(--app-border);
  background: rgba(14, 20, 34, 0.55);
}

.sync-loading-box p {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--app-muted);
  text-align: center;
}

.compact-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.compact-form.disabled {
  opacity: 0.45;
  pointer-events: none;
}

.phase-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.phase-segmented {
  display: inline-flex;
  padding: 3px;
  border-radius: 10px;
  background: rgba(11, 16, 28, 0.85);
  border: 1px solid var(--app-border);
}

.seg-btn {
  min-width: 72px;
  height: 30px;
  padding: 0 16px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--app-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease, box-shadow 150ms ease;
}

.seg-btn:hover {
  color: var(--app-text);
}

.seg-btn.active {
  background: var(--app-primary-gradient);
  color: #ffffff;
  box-shadow: 0 3px 10px -2px rgba(99, 102, 241, 0.5);
}

.form-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
}

.form-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.field-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-item label {
  font-size: 12.5px;
  font-weight: 550;
  color: var(--app-muted);
}

.field-item :deep(.el-select) {
  width: 100%;
}

.full-width-num {
  width: 100% !important;
}

.extra-panel {
  border: 1px solid var(--app-border);
  border-radius: 11px;
  background: rgba(14, 20, 34, 0.52);
  overflow: hidden;
}

.extra-panel.open {
  border-color: var(--app-border-strong);
}

.extra-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border: none;
  background: transparent;
  color: var(--app-muted);
  font-size: 12.5px;
  cursor: pointer;
  transition: color 140ms ease, background-color 140ms ease;
}

.extra-trigger:hover {
  color: var(--app-text);
  background: rgba(30, 42, 68, 0.3);
}

.extra-dot {
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  font-style: normal;
  font-size: 11px;
  background: rgba(99, 102, 241, 0.2);
  color: #c7d2fe;
}

.extra-chevron {
  transition: transform 170ms ease;
}

.extra-chevron.rotated {
  transform: rotate(180deg);
}

.extra-body {
  padding: 12px 14px 14px;
  border-top: 1px solid var(--app-border);
}

.dialog-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.foot-left {
  min-height: 28px;
  display: flex;
  align-items: center;
}

.estimate-pill {
  padding: 4px 11px;
  border-radius: 8px;
  font-size: 12.5px;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.28);
  color: #a7f3d0;
}

.estimate-pill strong {
  color: #ffffff;
}

.estimate-pill.stale {
  background: rgba(148, 163, 184, 0.1);
  border-color: var(--app-border);
  color: var(--app-muted);
}

.foot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

@media (max-width: 640px) {
  .form-grid-2,
  .form-grid-3 {
    grid-template-columns: 1fr;
  }
}
</style>
