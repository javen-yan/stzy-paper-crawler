import { save } from '@tauri-apps/plugin-dialog'
import { callCommand } from './client'
import type { ExportJob } from '../types/exports'

export async function exportTaskZipWithDialog(payload: {
  task_id: string
  default_name?: string
  file_paths?: string[]
}): Promise<ExportJob | null> {
  const defaultFileName = payload.default_name || `${payload.task_id}.zip`
  const destination = await save({
    title: '导出 ZIP 压缩包',
    defaultPath: defaultFileName,
    filters: [{ name: 'ZIP 压缩包', extensions: ['zip'] }],
  })
  if (!destination) {
    return null
  }
  return callCommand<ExportJob>('export_task_zip', {
    task_id: payload.task_id,
    file_paths: payload.file_paths,
    destination,
  })
}
