import { api } from './client'
import type { CatalogState } from '../types/catalogs'

export function fetchCatalogs() {
  return api<CatalogState>('/api/v1/catalogs')
}

export function refreshCatalogs() {
  return api<CatalogState>('/api/v1/catalogs/refresh', { method: 'POST' })
}
