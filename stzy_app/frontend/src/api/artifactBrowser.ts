import { api } from './client'

export interface ArtifactBrowserEntry {
  parent_path: string
  name: string
  extension?: string
  relative_path: string
  item_type: 'folder' | 'file'
  size_bytes?: number | null
  modified_at?: number | null
  media_type?: string | null
}

export interface ArtifactBrowserListResult {
  current_path: string
  items: ArtifactBrowserEntry[]
}

export interface ArtifactBrowserListParams {
  path?: string
  task_id?: string
  signal?: AbortSignal
}

export interface ArtifactBrowserSearchParams extends ArtifactBrowserListParams {
  filter?: string
  deep?: boolean
}

function queryString(params: Record<string, unknown>) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  return query.toString()
}

export function listArtifactBrowser(params: ArtifactBrowserListParams = {}) {
  const query = queryString({ path: params.path, task_id: params.task_id })
  return api<ArtifactBrowserListResult>(`/api/v1/artifacts/browser/list${query ? `?${query}` : ''}`, { signal: params.signal })
}

export function searchArtifactBrowser(params: ArtifactBrowserSearchParams) {
  const query = queryString({
    path: params.path,
    task_id: params.task_id,
    filter: params.filter,
    deep: params.deep ? 1 : undefined,
  })
  return api<{ items: ArtifactBrowserEntry[] }>(`/api/v1/artifacts/browser/search${query ? `?${query}` : ''}`, { signal: params.signal })
}

export function artifactPreviewUrl(path: string, taskId?: string) {
  const query = queryString({ path, task_id: taskId })
  return `/api/v1/artifacts/browser/preview?${query}`
}

export function artifactDownloadUrl(path: string, taskId?: string) {
  const query = queryString({ path, task_id: taskId })
  return `/api/v1/artifacts/browser/download?${query}`
}
