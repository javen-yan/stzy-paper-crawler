import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '../layouts/AppShell.vue'
import AuthLayout from '../layouts/AuthLayout.vue'

const LoginView = () => import('../views/LoginView.vue')
const TaskCenterView = () => import('../views/TaskCenterView.vue')
const TaskDetailView = () => import('../views/TaskDetailView.vue')
const FileLibraryView = () => import('../views/FileLibraryView.vue')
const AccountsView = () => import('../views/AccountsView.vue')
const SettingsView = () => import('../views/SettingsView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/tasks' },
    {
      path: '/login',
      component: AuthLayout,
      children: [{ path: '', component: LoginView }],
    },
    {
      path: '/',
      component: AppShell,
      children: [
        { path: 'tasks', component: TaskCenterView },
        { path: 'tasks/:id', component: TaskDetailView, props: true },
        { path: 'files', component: FileLibraryView },
        { path: 'accounts', component: AccountsView },
        { path: 'settings', component: SettingsView },
      ],
    },
  ],
})

export default router
