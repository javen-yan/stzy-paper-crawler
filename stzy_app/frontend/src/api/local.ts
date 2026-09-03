import { api, jsonBody } from './client'

export function chooseDirectory(initialDir = '') {
  return api<{ path: string }>('/api/v1/local/choose-directory', {
    method: 'POST',
    ...jsonBody({ initial_dir: initialDir }),
  })
}

export function openLocalPath(path: string) {
  return api<{ ok: boolean }>('/api/v1/local/open', {
    method: 'POST',
    ...jsonBody({ path }),
  })
}
