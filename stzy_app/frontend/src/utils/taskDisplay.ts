import type { Task } from '../types/tasks'

const PHASE_LABELS: Record<string, string> = {
  '200': '初中',
  '300': '高中',
}

const FILTER_KEYS = [
  'provinces',
  'grades',
  'terms',
  'years',
  'scenes',
  'ranks',
]

export function taskDisplayName(task: Task, fallbackIndex?: number) {
  const explicitTitle = String(task.title || task.spec?.title || '').trim()
  if (explicitTitle) return explicitTitle

  const backendDisplayName = String(task.task_display_name || '').trim()
  if (backendDisplayName && backendDisplayName !== task.id) return backendDisplayName

  const generated = taskFilterDisplayName(task)
  if (generated) return generated

  return fallbackFilterName(fallbackIndex)
}

export function taskFilterDisplayName(task: Task) {
  const spec = task.spec || {}
  const settings = spec.settings || {}
  const filters = spec.filters || {}
  const filterLabels = (spec.filter_labels || {}) as Record<string, unknown>
  const parts: string[] = []

  const phaseCode = String(settings.study_phase_code || '')
  if (phaseCode) parts.push(PHASE_LABELS[phaseCode] || phaseCode)

  const subjects = Array.isArray(spec.subjects) ? spec.subjects : []
  const subjectNames = subjects
    .map((subject) => String(subject.name || subject.code || '').trim())
    .filter((name) => name && name !== '不限')
  if (subjectNames.length) parts.push(compactValues(subjectNames))

  for (const key of FILTER_KEYS) {
    const values = toArray(filters[key])
    if (!values.length) continue
    const labels = toArray(filterLabels[key])
    if (labels.length) parts.push(compactValues(labels))
    else if (!values.every((value) => looksLikeCode(value))) parts.push(compactValues(values))
  }

  const fileType = String(settings.file_type || '').trim()
  if (fileType) parts.push(fileType)

  return unique(parts.filter(Boolean)).join(' / ')
}

export function fallbackFilterName(index?: number) {
  if (typeof index !== 'number' || index < 0) return '筛选任务'
  return `筛选 ${alphaIndex(index)}`
}

function toArray(value: unknown): string[] {
  if (value == null) return []
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  const text = String(value)
  return text ? [text] : []
}

function compactValues(values: string[]) {
  if (values.length <= 2) return values.join('、')
  return `${values.slice(0, 2).join('、')}等`
}

function unique(values: string[]) {
  return Array.from(new Set(values))
}

function looksLikeCode(value: string) {
  return /^[0-9A-Za-z_-]+$/.test(value)
}

function alphaIndex(index: number) {
  let value = index
  let result = ''
  do {
    result = String.fromCharCode(65 + (value % 26)) + result
    value = Math.floor(value / 26) - 1
  } while (value >= 0)
  return result
}
