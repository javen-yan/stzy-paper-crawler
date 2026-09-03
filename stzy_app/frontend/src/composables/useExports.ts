import { ref } from 'vue'
import { createZipExport, exportDownloadUrl, fetchExport } from '../api/exports'
import type { ExportJob } from '../types/exports'

const currentExport = ref<ExportJob | null>(null)

export function useExports() {
  async function createTaskZip(taskId: string, filePaths: string[] = []) {
    currentExport.value = await createZipExport({ task_id: taskId, file_paths: filePaths })
    return currentExport.value
  }

  async function refreshExport() {
    if (!currentExport.value) return null
    currentExport.value = await fetchExport(currentExport.value.id)
    return currentExport.value
  }

  return { currentExport, createTaskZip, refreshExport, exportDownloadUrl }
}
