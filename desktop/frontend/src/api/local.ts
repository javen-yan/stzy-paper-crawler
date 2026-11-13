import { open } from '@tauri-apps/plugin-dialog'
import { callCommand } from './client'

export async function chooseDirectory(initialDir = ''): Promise<{ path: string }> {
  const selected = await open({
    title: '选择输出目录',
    directory: true,
    multiple: false,
    defaultPath: initialDir || undefined,
  })
  if (!selected || Array.isArray(selected)) {
    return { path: '' }
  }
  return { path: selected }
}

export async function chooseFile(title = '选择文件', initialPath = ''): Promise<{ path: string }> {
  const selected = await open({
    title,
    directory: false,
    multiple: false,
    defaultPath: initialPath || undefined,
  })
  if (!selected || Array.isArray(selected)) {
    return { path: '' }
  }
  return { path: selected }
}

export function openLocalPath(path: string, options: { taskId?: string; reveal?: boolean } = {}) {
  return callCommand<{ ok: boolean; path: string }>('open_local_path', {
    path,
    task_id: options.taskId,
    reveal: options.reveal ?? false,
  })
}

export function openExternalUrl(url: string) {
  return callCommand<{ ok: boolean; url: string }>('open_external_url', { url })
}
