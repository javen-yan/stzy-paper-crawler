export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let csrfToken = ''
let unauthorizedHandler: (() => void) | null = null

export function setCsrfToken(token: string) {
  csrfToken = token
}

export function getCsrfToken() {
  return csrfToken
}

export function onUnauthorized(handler: () => void) {
  unauthorizedHandler = handler
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {})
  if (!(init.body instanceof FormData) && init.body !== undefined) {
    headers.set('content-type', 'application/json')
  }
  const method = (init.method || 'GET').toUpperCase()
  if (csrfToken && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers.set('x-csrf-token', csrfToken)
  }
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }))
    if (response.status === 401) unauthorizedHandler?.()
    throw new ApiError(payload.detail || response.statusText || '请求失败', response.status)
  }
  const text = await response.text()
  return (text ? JSON.parse(text) : {}) as T
}

export function jsonBody(value: unknown): RequestInit {
  return { body: JSON.stringify(value) }
}
