export interface CatalogOption {
  code: string
  name: string
}

export interface TagOption {
  field: string
  code: string
  name: string
}

export interface CatalogState {
  study_phases?: Record<string, string>
  subjects?: Record<string, Record<string, string>>
  catalogs?: Record<string, Record<string, CatalogOption[]>>
  [key: string]: unknown
}
