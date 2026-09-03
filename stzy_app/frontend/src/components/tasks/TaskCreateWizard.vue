<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, UserRoundCog } from 'lucide-vue-next'
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
const ALL_VALUE = '__all__'

const visible = ref(false)
const step = ref(0)
const advancedPanels = ref<string[]>([])
const catalog = ref<CatalogState | null>(null)
const catalogLoading = ref(false)
const estimateLoading = ref(false)
const estimateResult = ref<TaskEstimateResult | null>(null)
const estimatedSignature = ref('')
const quick = reactive({
  studyPhase: '300',
  subject: ALL_VALUE,
  province: ALL_VALUE,
  year: ALL_VALUE,
  term: ALL_VALUE,
  scene: ALL_VALUE,
})
const advanced = reactive({
  studyPhase: '300',
  subject: ALL_VALUE,
  scene: ALL_VALUE,
  year: ALL_VALUE,
  rank: ALL_VALUE,
  province: ALL_VALUE,
  grade: ALL_VALUE,
  term: ALL_VALUE,
})
const form = reactive<TaskCreateForm>({
  title: '',
  mode: 'estimate',
  studyPhase: '300',
  fileType: 'PDF',
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
const abnormalAccounts = computed(() => props.accounts.filter((account) => !account.usable || !account.enabled))
const canSubmit = computed(() => usableAccounts.value.length > 0)
const selectedFilterSummary = computed(() => {
  const parts = [
    optionLabel(advancedSubjectSelectOptions.value, advanced.subject),
    optionLabel(optionList('provinceCode', '地区不限', advanced.studyPhase), advanced.province),
    optionLabel(optionList('yearCode', '年份不限', advanced.studyPhase), advanced.year),
    optionLabel(optionList('termCode', '年级学期不限', advanced.studyPhase), advanced.term),
    optionLabel(optionList('sceneCode', '场景不限', advanced.studyPhase), advanced.scene),
  ].filter((item) => item && !item.endsWith('不限') && item !== '不限')
  return parts.length ? parts.join(' / ') : '不限'
})
const estimateStats = computed(() => estimateResult.value?.stats || {})
const estimatedResources = computed(() => numberStat(estimateStats.value.resources_seen))
const estimatedCombos = computed(() => `${numberStat(estimateStats.value.completed_combos)}/${numberStat(estimateStats.value.total_combos)}`)
const estimateIssues = computed(() => numberStat(estimateStats.value.failed))
const canStartDownload = computed(() => Boolean(estimateResult.value && estimatedSignature.value === currentFilterSignature()))
const studyPhaseOptions = computed(() => {
  const phases = catalog.value?.study_phases
  if (phases && typeof phases === 'object') return Object.entries(phases).map(([value, label]) => ({ value, label: String(label) }))
  return [
    { value: '200', label: '初中' },
    { value: '300', label: '高中' },
  ]
})

const quickSubjectSelectOptions = computed(() => [{ value: ALL_VALUE, label: '学科不限' }, ...subjectOptionsForPhase(quick.studyPhase)])
const advancedSubjectSelectOptions = computed(() => [{ value: ALL_VALUE, label: '学科不限' }, ...subjectOptionsForPhase(advanced.studyPhase)])

function subjectOptionsForPhase(phase: string) {
  const subjects = catalog.value?.subjects as Record<string, Record<string, string>> | undefined
  const current = subjects?.[phase] || {}
  return Object.entries(current).map(([value, label]) => ({ value, label }))
}

function tagOptions(field: string, phase = advanced.studyPhase) {
  const catalogs = catalog.value?.catalogs as Record<string, Record<string, Array<{ code: string; name: string }>>> | undefined
  const items = catalogs?.[phase]?.[field] || []
  return items.map((item) => ({ value: item.code, label: item.name }))
}

function optionList(field: string, allLabel: string, phase = advanced.studyPhase) {
  return [{ value: ALL_VALUE, label: allLabel }, ...tagOptions(field, phase)]
}

function optionLabel(options: Array<{ value: string; label: string }>, value: string) {
  return options.find((item) => item.value === value)?.label || ''
}

function findOptionValue(options: Array<{ value: string; label: string }>, label: string) {
  const target = label.trim().replace('市', '')
  return options.find((item) => item.label.trim().replace('市', '') === target)?.value || ALL_VALUE
}

function resetAndOpen() {
  step.value = 0
  advancedPanels.value = []
  estimateResult.value = null
  estimatedSignature.value = ''
  form.mode = 'estimate'
  quick.studyPhase = '300'
  quick.subject = ALL_VALUE
  quick.province = ALL_VALUE
  quick.year = ALL_VALUE
  quick.term = ALL_VALUE
  quick.scene = ALL_VALUE
  advanced.studyPhase = '300'
  advanced.subject = ALL_VALUE
  advanced.scene = ALL_VALUE
  advanced.year = ALL_VALUE
  advanced.rank = ALL_VALUE
  advanced.province = ALL_VALUE
  advanced.grade = ALL_VALUE
  advanced.term = ALL_VALUE
  visible.value = true
  loadCatalogs()
}

function submit() {
  syncFormFromAdvanced()
  visible.value = false
  emit('submit', { ...form, mode: 'crawl' })
}

async function runEstimate() {
  syncFormFromAdvanced()
  estimateLoading.value = true
  estimateResult.value = null
  try {
    estimateResult.value = await estimateTask({ ...form, mode: 'estimate' })
    estimatedSignature.value = currentFilterSignature()
    toast.success('预估完成')
  } catch (error) {
    toast.error(error, '预估失败')
  } finally {
    estimateLoading.value = false
  }
}

function numberStat(value: unknown) {
  const numeric = Number(value || 0)
  return Number.isFinite(numeric) ? numeric : 0
}

function valueArray(value: string) {
  return value && value !== ALL_VALUE ? [value] : []
}

function applyQuickFilter() {
  if ([quick.subject, quick.province, quick.year, quick.term, quick.scene].every((value) => value === ALL_VALUE)) {
    toast.error('请选择快速筛选条件')
    return
  }
  advanced.studyPhase = quick.studyPhase
  advanced.subject = quick.subject
  advanced.province = quick.province
  advanced.year = quick.year
  advanced.term = quick.term
  advanced.scene = quick.scene
  if (quick.term !== ALL_VALUE) {
    const termLabel = optionLabel(optionList('termCode', '年级学期不限', advanced.studyPhase), quick.term)
    const gradeName = termLabel.endsWith('上') || termLabel.endsWith('下') ? termLabel.slice(0, -1) : termLabel
    advanced.grade = findOptionValue(optionList('gradeCode', '年级不限', advanced.studyPhase), gradeName)
  } else {
    advanced.grade = ALL_VALUE
  }
  syncFormFromAdvanced()
  resetEstimateResult()
  toast.success('快速筛选已应用')
}

function changeQuickPhase() {
  advanced.studyPhase = quick.studyPhase
  changeAdvancedPhase()
  quick.subject = ALL_VALUE
  quick.province = ALL_VALUE
  quick.year = ALL_VALUE
  quick.term = ALL_VALUE
  quick.scene = ALL_VALUE
}

function changeAdvancedPhase() {
  advanced.subject = ALL_VALUE
  advanced.scene = ALL_VALUE
  advanced.year = ALL_VALUE
  advanced.rank = ALL_VALUE
  advanced.province = ALL_VALUE
  advanced.grade = ALL_VALUE
  advanced.term = ALL_VALUE
  syncFormFromAdvanced()
  resetEstimateResult()
}

function syncFormFromAdvanced() {
  form.studyPhase = advanced.studyPhase
  form.subjects = valueArray(advanced.subject)
  form.scenes = valueArray(advanced.scene)
  form.grades = valueArray(advanced.grade)
  form.terms = valueArray(advanced.term)
  form.provinces = valueArray(advanced.province)
  form.years = valueArray(advanced.year)
  form.ranks = valueArray(advanced.rank)
  form.subjectLabels = Object.fromEntries(
    form.subjects.map((code) => [code, optionLabel(advancedSubjectSelectOptions.value, code)]).filter(([, label]) => label),
  )
  form.filterLabels = {
    scenes: selectedLabels(optionList('sceneCode', '不限', advanced.studyPhase), form.scenes),
    grades: selectedLabels(optionList('gradeCode', '不限', advanced.studyPhase), form.grades),
    terms: selectedLabels(optionList('termCode', '不限', advanced.studyPhase), form.terms),
    provinces: selectedLabels(optionList('provinceCode', '不限', advanced.studyPhase), form.provinces),
    years: selectedLabels(optionList('yearCode', '不限', advanced.studyPhase), form.years),
    ranks: selectedLabels(optionList('rank', '不限', advanced.studyPhase), form.ranks),
  }
}

function selectedLabels(options: Array<{ value: string; label: string }>, values: string[]) {
  return values
    .map((value) => optionLabel(options, value))
    .filter((label) => label && !label.endsWith('不限') && label !== '不限')
}

function resetEstimateResult() {
  estimateResult.value = null
  estimatedSignature.value = ''
}

function currentFilterSignature() {
  return JSON.stringify({
    studyPhase: advanced.studyPhase,
    subject: advanced.subject,
    scene: advanced.scene,
    year: advanced.year,
    rank: advanced.rank,
    province: advanced.province,
    grade: advanced.grade,
    term: advanced.term,
  })
}

async function loadCatalogs(force = false) {
  if (catalog.value && !force) return
  catalogLoading.value = true
  try {
    catalog.value = force ? await refreshCatalogs() : await fetchCatalogs()
  } catch (error) {
    toast.error(error, '分类加载失败')
  } finally {
    catalogLoading.value = false
  }
}
</script>

<template>
  <el-button type="primary" size="large" :icon="Plus" @click="resetAndOpen">新建下载任务</el-button>

  <el-drawer v-model="visible" size="min(1180px, 96vw)" title="新建下载任务" class="task-create-drawer" destroy-on-close>
    <el-steps :active="step" finish-status="success" align-center class="compact-steps">
      <el-step title="账号检查" />
      <el-step title="筛选预估 / 下载" />
    </el-steps>

    <section class="wizard-body">
      <div v-if="step === 0" class="stack">
        <el-alert
          v-if="canSubmit"
          :title="`可用账号 ${usableAccounts.length} 个。`"
          type="success"
          show-icon
          :closable="false"
        />
        <el-alert
          v-else
          title="还没有可用账号，先添加账号。"
          type="warning"
          show-icon
          :closable="false"
        />
        <el-descriptions :column="1" border>
          <el-descriptions-item label="可用账号">{{ usableAccounts.length }}</el-descriptions-item>
          <el-descriptions-item label="异常/停用">{{ abnormalAccounts.length }}</el-descriptions-item>
        </el-descriptions>
        <el-button v-if="!canSubmit" :icon="UserRoundCog" @click="router.push('/accounts')">去添加账号</el-button>
      </div>

      <el-form v-else label-position="top" class="wizard-form task-create-form">
        <el-alert
          title="先预估数量，确认后再下载。"
          type="info"
          show-icon
          :closable="false"
          class="span-full"
        />

        <div class="task-form-section span-full">
          <div class="section-title">
            <strong>1 筛选试卷</strong>
            <div class="section-title-actions">
              <span>快速 + 高级</span>
              <el-button text type="primary" size="small" :loading="catalogLoading" @click="loadCatalogs(true)">刷新分类</el-button>
            </div>
          </div>
          <el-form-item label="任务名称" class="task-title-field">
            <el-input v-model="form.title" placeholder="可选，例如：高一数学期末预估" />
          </el-form-item>
          <div class="quick-filter">
            <div class="quick-filter-head">
              <span class="quick-filter-title">快速筛选</span>
            </div>
            <div class="quick-filter-fields">
              <el-select v-model="quick.studyPhase" class="quick-filter-input" placeholder="学段" @change="changeQuickPhase">
                <el-option v-for="item in studyPhaseOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="quick.subject" class="quick-filter-input" filterable placeholder="学科">
                <el-option v-for="item in quickSubjectSelectOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="quick.province" class="quick-filter-input" filterable placeholder="地区">
                <el-option v-for="item in optionList('provinceCode', '地区不限', quick.studyPhase)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="quick.year" class="quick-filter-input" filterable placeholder="年份">
                <el-option v-for="item in optionList('yearCode', '年份不限', quick.studyPhase)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="quick.term" class="quick-filter-input" filterable placeholder="年级学期">
                <el-option v-for="item in optionList('termCode', '年级学期不限', quick.studyPhase)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="quick.scene" class="quick-filter-input" filterable placeholder="场景">
                <el-option v-for="item in optionList('sceneCode', '场景不限', quick.studyPhase)" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-button type="primary" class="quick-filter-button" @click="applyQuickFilter">应用</el-button>
            </div>
          </div>
          <div class="filter-panel-footer">
            <span>当前筛选：{{ selectedFilterSummary }}</span>
          </div>
        </div>

        <el-collapse v-model="advancedPanels" class="span-full task-advanced-collapse">
          <el-collapse-item name="advancedFilters">
            <template #title>
              <span class="collapse-title">高级筛选：学段 / 学科 / 场景 / 年份 / 等级 / 地区 / 年级 / 学期</span>
            </template>
            <div class="filter-list">
              <div class="filter-row">
                <span class="filter-row-label">学段</span>
                <el-radio-group v-model="advanced.studyPhase" class="filter-toggle" @change="changeAdvancedPhase">
                  <el-radio-button v-for="item in studyPhaseOptions" :key="item.value" :label="item.value">{{ item.label }}</el-radio-button>
                </el-radio-group>
              </div>
              <div class="filter-row">
                <span class="filter-row-label">学科</span>
                <el-radio-group v-model="advanced.subject" class="filter-toggle">
                  <el-radio-button v-for="item in advancedSubjectSelectOptions" :key="item.value" :label="item.value">{{ item.label }}</el-radio-button>
                </el-radio-group>
              </div>
              <div class="filter-row">
                <span class="filter-row-label">场景</span>
                <el-radio-group v-model="advanced.scene" class="filter-toggle">
                  <el-radio-button v-for="item in optionList('sceneCode', '不限', advanced.studyPhase)" :key="item.value" :label="item.value">{{ item.label }}</el-radio-button>
                </el-radio-group>
              </div>
              <div class="filter-row">
                <span class="filter-row-label">年份</span>
                <el-radio-group v-model="advanced.year" class="filter-toggle">
                  <el-radio-button v-for="item in optionList('yearCode', '不限', advanced.studyPhase)" :key="item.value" :label="item.value">{{ item.label }}</el-radio-button>
                </el-radio-group>
              </div>
              <div class="filter-row">
                <span class="filter-row-label">等级</span>
                <el-radio-group v-model="advanced.rank" class="filter-toggle">
                  <el-radio-button v-for="item in optionList('rank', '不限', advanced.studyPhase)" :key="item.value" :label="item.value">{{ item.label }}</el-radio-button>
                </el-radio-group>
              </div>
              <div class="filter-row">
                <span class="filter-row-label">地区</span>
                <el-radio-group v-model="advanced.province" class="filter-toggle">
                  <el-radio-button v-for="item in optionList('provinceCode', '不限', advanced.studyPhase)" :key="item.value" :label="item.value">{{ item.label }}</el-radio-button>
                </el-radio-group>
              </div>
              <div class="filter-row">
                <span class="filter-row-label">年级</span>
                <el-radio-group v-model="advanced.grade" class="filter-toggle">
                  <el-radio-button v-for="item in optionList('gradeCode', '不限', advanced.studyPhase)" :key="item.value" :label="item.value">{{ item.label }}</el-radio-button>
                </el-radio-group>
              </div>
              <div class="filter-row">
                <span class="filter-row-label">学期</span>
                <el-radio-group v-model="advanced.term" class="filter-toggle">
                  <el-radio-button v-for="item in optionList('termCode', '不限', advanced.studyPhase)" :key="item.value" :label="item.value">{{ item.label }}</el-radio-button>
                </el-radio-group>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>

        <div class="task-form-section span-full task-control-panel">
          <div class="section-title">
            <strong>2 执行任务</strong>
            <span class="task-context">当前筛选：{{ selectedFilterSummary }}</span>
          </div>
          <div class="action-grid status-action-flow">
            <el-button class="task-control-action secondary-action" size="large" :loading="estimateLoading" :disabled="!canSubmit" @click="runEstimate">
              预估数量
            </el-button>
            <el-button class="task-control-action primary-action" type="primary" size="large" :loading="submitting" :disabled="!canSubmit || !canStartDownload" @click="submit">
              开始下载
            </el-button>
          </div>
          <div class="estimate-inline-result">
            <template v-if="estimateResult">
              <span>条件组合：{{ estimatedCombos }}</span>
              <span>匹配试卷：{{ estimatedResources }}</span>
              <span>异常数量：{{ estimateIssues }}</span>
              <span v-if="!canStartDownload" class="warning-text">筛选已变化，请重新预估。</span>
            </template>
            <template v-else>
              <span>先预估数量，确认后再下载。</span>
            </template>
          </div>
        </div>

      </el-form>

    </section>

    <template #footer>
      <div class="drawer-footer">
        <span class="drawer-footer-hint">
          {{ step === 0 ? '确认账号池可用' : '筛选并预估/下载' }}
        </span>
        <div class="drawer-footer-actions">
          <el-button @click="visible = false">取消</el-button>
          <el-button v-if="step > 0" @click="step -= 1">上一步</el-button>
          <el-button v-if="step < 1" type="primary" :disabled="!canSubmit" @click="step += 1">下一步</el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>
