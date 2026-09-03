import { api, jsonBody } from './client'
import type { ExportJob } from '../types/exports'

export function createZipExport(payload: { task_id: string; file_paths?: string[] }) {
  return api<ExportJob>('/api/v1/exports', { method: 'POST', ...jsonBody(payload) })
}

export function fetchExport(exportId: string) {
  return api<ExportJob>(`/api/v1/exports/${encodeURIComponent(exportId)}`)
}

export function exportDownloadUrl(exportId: string) {
  return `/api/v1/exports/${encodeURIComponent(exportId)}/download`
}
