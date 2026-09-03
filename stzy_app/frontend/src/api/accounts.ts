import { api, jsonBody } from './client'
import type { Account, AccountPayload, AccountImportPayload, PhoneLoginPayload } from '../types/accounts'

export function listAccounts() {
  return api<{ items: Account[] }>('/api/v1/accounts')
}

export function saveAccount(payload: AccountPayload) {
  return api<Account>('/api/v1/accounts', { method: 'POST', ...jsonBody(payload) })
}

export function importAccount(payload: AccountImportPayload) {
  return api<Account>('/api/v1/accounts/import', { method: 'POST', ...jsonBody(payload) })
}

export function phoneLogin(payload: PhoneLoginPayload) {
  return api<Account>('/api/v1/accounts/phone-login', { method: 'POST', ...jsonBody(payload) })
}

export function fetchAuthScript() {
  return api<{ script: string }>('/api/v1/accounts/auth-script')
}

export function setAccountEnabled(name: string, enabled: boolean) {
  return api<Account>(`/api/v1/accounts/${encodeURIComponent(name)}/enabled`, {
    method: 'POST',
    ...jsonBody({ enabled }),
  })
}

export function verifyAccount(name: string) {
  return api<Account>(`/api/v1/accounts/${encodeURIComponent(name)}/verify`, { method: 'POST' })
}

export function deleteAccount(name: string) {
  return api<{ ok: boolean }>(`/api/v1/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' })
}
