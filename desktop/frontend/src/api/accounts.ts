import { callCommand } from './client'
import type { Account, AccountPayload, AccountImportPayload, PhoneLoginPayload } from '../types/accounts'

export function listAccounts() {
  return callCommand<{ items: Account[] }>('list_accounts')
}

export function saveAccount(payload: AccountPayload) {
  return callCommand<Account>('save_account', { payload })
}

export function importAccount(payload: AccountImportPayload) {
  return callCommand<Account>('import_account', { payload })
}

export function phoneLogin(payload: PhoneLoginPayload) {
  return callCommand<Account>('phone_login', { payload })
}

export function fetchAuthScript() {
  return callCommand<{ script: string }>('get_auth_script')
}

export function setAccountEnabled(name: string, enabled: boolean) {
  return callCommand<Account>('set_account_enabled', { name, enabled })
}

export function verifyAccount(name: string) {
  return callCommand<Account>('verify_account', { name })
}

export function deleteAccount(name: string) {
  return callCommand<{ ok: boolean }>('delete_account', { name })
}
