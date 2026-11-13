import { save } from '@tauri-apps/plugin-dialog'
import { callCommand, stzyFileUrl } from './client'

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

export function listArtifactBrowser(params: ArtifactBrowserListParams = {}) {
  return callCommand<ArtifactBrowserListResult>('browse_task_files', {
    path: params.path,
    task_id: params.task_id,
  })
}

export function searchArtifactBrowser(params: ArtifactBrowserSearchParams) {
  return callCommand<{ items: ArtifactBrowserEntry[] }>('search_task_files', {
    path: params.path,
    task_id: params.task_id,
    filter: params.filter,
    deep: params.deep,
  })
}

export function artifactPreviewUrl(path: string, taskId?: string) {
  return stzyFileUrl('browser', { path, task_id: taskId })
}

export async function saveBrowserFileAs(
  relativePath: string,
  suggestedName: string,
  taskId?: string,
): Promise<{ saved: boolean; destination?: string; size_bytes?: number }> {
  const destination = await save({
    title: '保存文件',
    defaultPath: suggestedName,
  })
  if (!destination) {
    return { saved: false }
  }
  return callCommand('save_browser_file', {
    path: relativePath,
    task_id: taskId,
    destination,
  })
}
