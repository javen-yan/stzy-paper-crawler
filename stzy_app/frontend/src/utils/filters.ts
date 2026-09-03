import type { CatalogState } from '../types/catalogs'
import type { Task } from '../types/tasks'

interface FilterFieldMeta {
  key: string
  label: string
  catalogField?: string
}

const FILTER_FIELDS: FilterFieldMeta[] = [
  { key: 'scenes', label: '场景', catalogField: 'sceneCode' },
  { key: 'years', label: '年份', catalogField: 'yearCode' },
  { key: 'ranks', label: '试卷等级', catalogField: 'rank' },
  { key: 'provinces', label: '地区', catalogField: 'provinceCode' },
  { key: 'grades', label: '年级', catalogField: 'gradeCode' },
  { key: 'terms', label: '学期', catalogField: 'termCode' },
]

const EMPTY_LABEL = '不限'

export interface ResolvedFilterRow {
  key: string
  label: string
  value: string
}

function toArray(value: unknown): string[] {
  if (value == null) return []
  if (Array.isArray(value)) return value.map(String)
  return [String(value)]
}

function resolveCodes(codes: string[], options: Array<{ code: string; name: string }> | undefined): string {
  if (!codes.length) return EMPTY_LABEL
  const resolved = codes.map((code) => {
    const option = options?.find((item) => item.code === code)
    return option?.name || code
  })
  return resolved.join('、')
}

export function resolveTaskFilters(task: Task, catalog: CatalogState): ResolvedFilterRow[] {
  const rows: ResolvedFilterRow[] = []
  const spec = task.spec || {}
  const filters = spec.filters || {}
  const settings = spec.settings || {}
  const subjects = spec.subjects || []

  for (const field of FILTER_FIELDS) {
    const value = (filters as Record<string, unknown>)[field.key]
    if (value == null) continue
    const codes = toArray(value)
    const options = field.catalogField ? catalog.catalogs?.[settings.study_phase_code as string]?.[field.catalogField] : undefined
    const resolved = resolveCodes(codes, options)
    if (resolved === EMPTY_LABEL) continue
    rows.push({ key: field.key, label: field.label, value: resolved })
  }

  const phaseCode = String((settings as Record<string, unknown>).study_phase_code || '')
  if (phaseCode) {
    rows.unshift({
      key: 'study_phase',
      label: '学段',
      value: catalog.study_phases?.[phaseCode] || phaseCode,
    })
  }

  if (Array.isArray(subjects) && subjects.length) {
    const names = subjects.map((subject) => subject.name || subject.code || '').filter(Boolean)
    if (names.length) {
      rows.push({ key: 'subjects', label: '学科', value: names.join('、') })
    }
  }

  return rows
}

export function readableStringValue(value: unknown): string {
  if (value == null) return EMPTY_LABEL
  if (Array.isArray(value)) return value.length ? value.map((v) => String(v)).join('、') : EMPTY_LABEL
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
