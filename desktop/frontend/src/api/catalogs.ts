import { callCommand } from './client'
import type { CatalogState } from '../types/catalogs'

export function fetchCatalogs() {
  return callCommand<CatalogState>('get_catalogs')
}

export function refreshCatalogs() {
  return callCommand<CatalogState>('refresh_catalogs')
}
