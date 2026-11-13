import { invoke } from '@tauri-apps/api/core'

export class ApiError extends Error {
  status: number

  constructor(message: string, status = 500) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface RawCommandError {
  detail?: string
  status?: number
  message?: string
}

export async function callCommand<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  try {
    return await invoke<T>(command, args)
  } catch (err) {
    if (err && typeof err === 'object') {
      const raw = err as RawCommandError
      const msg = raw.detail || raw.message || '操作失败'
      const status = typeof raw.status === 'number' ? raw.status : 500
      throw new ApiError(msg, status)
    }
    throw new ApiError(typeof err === 'string' ? err : '操作失败', 500)
  }
}

export function stzyFileUrl(
  route: 'browser' | 'artifact',
  params: Record<string, string | undefined>,
): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      query.set(key, value)
    }
  })
  const isWindows = typeof navigator !== 'undefined' && /windows/i.test(navigator.userAgent)
  const origin = isWindows ? 'http://stzyfile.localhost' : 'stzyfile://localhost'
  const qs = query.toString()
  return `${origin}/${route}${qs ? `?${qs}` : ''}`
}
