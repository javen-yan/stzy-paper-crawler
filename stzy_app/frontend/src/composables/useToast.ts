import { ElMessage } from 'element-plus'

export function useToast() {
  return {
    success(message = '操作已提交') {
      ElMessage.success(message)
    },
    error(error: unknown, fallback = '操作失败') {
      const message = error instanceof Error ? error.message : String(error || fallback)
      ElMessage.error(message)
    },
    info(message: string) {
      ElMessage.info(message)
    },
  }
}
