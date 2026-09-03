import { computed, readonly, ref } from 'vue'
import { useRouter } from 'vue-router'
import { bootstrap, fetchSession, login as loginApi, logout as logoutApi } from '../api/auth'
import { onUnauthorized, setCsrfToken } from '../api/client'
import { useToast } from './useToast'
import type { SessionInfo } from '../types/auth'

const session = ref<SessionInfo>({ authenticated: false })
const booted = ref(false)

export function useAuth() {
  const router = useRouter()
  const toast = useToast()

  onUnauthorized(() => {
    session.value = { authenticated: false }
    setCsrfToken('')
    if (router.currentRoute.value.path !== '/login') router.replace('/login')
  })

  async function initialize(mode?: string) {
    const token = new URLSearchParams(location.hash.split('?')[1] || '').get('token')
    if (token && mode === 'gui') {
      session.value = await bootstrap(token)
      history.replaceState(null, '', '/tasks')
    } else {
      session.value = await fetchSession()
    }
    booted.value = true
    return session.value
  }

  async function login(password: string) {
    session.value = await loginApi(password)
    toast.success('登录成功')
    await router.replace('/tasks')
  }

  async function logout() {
    await logoutApi()
    session.value = { authenticated: false }
    await router.replace('/login')
  }

  return {
    session: readonly(session),
    booted: readonly(booted),
    authenticated: computed(() => Boolean(session.value.authenticated)),
    initialize,
    login,
    logout,
  }
}
