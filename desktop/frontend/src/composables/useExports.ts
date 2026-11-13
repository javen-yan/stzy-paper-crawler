import { ref } from 'vue'
import { exportTaskZipWithDialog } from '../api/exports'
import type { ExportJob } from '../types/exports'

const currentExport = ref<ExportJob | null>(null)

export function useExports() {
  async function createTaskZip(taskId: string, filePaths: string[] = [], defaultName?: string) {
    const job = await exportTaskZipWithDialog({
      task_id: taskId,
      default_name: defaultName,
      file_paths: filePaths,
    })
    if (job) {
      currentExport.value = job
    }
    return job
  }

  return { currentExport, createTaskZip }
}
