<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import AccountEditor from '../components/accounts/AccountEditor.vue'
import AccountTable from '../components/accounts/AccountTable.vue'
import EmptyState from '../components/common/EmptyState.vue'
import { deleteAccount, importAccount, listAccounts, phoneLogin, setAccountEnabled, verifyAccount } from '../api/accounts'
import { useToast } from '../composables/useToast'
import type { Account, AccountImportPayload, PhoneLoginPayload } from '../types/accounts'

const toast = useToast()
const accounts = ref<Account[]>([])
const loading = ref(false)

async function refresh() {
  accounts.value = (await listAccounts()).items
}

async function run(work: () => Promise<void>, success: string) {
  loading.value = true
  try {
    await work()
    await refresh()
    toast.success(success)
  } catch (error) {
    toast.error(error)
  } finally {
    loading.value = false
  }
}

async function handlePhoneLogin(payload: PhoneLoginPayload) {
  await run(() => phoneLogin(payload).then(() => undefined), '账号已登录并保存')
}

async function handleImport(payload: AccountImportPayload) {
  await run(() => importAccount(payload).then(() => undefined), '凭据已导入')
}

async function handleVerify(account: Account) {
  await run(() => verifyAccount(account.name).then(() => undefined), '验证已完成')
}

async function handleEnabled(account: Account, enabled: boolean) {
  await run(() => setAccountEnabled(account.name, enabled).then(() => undefined), enabled ? '账号已启用' : '账号已停用')
}

async function handleDelete(account: Account) {
  await ElMessageBox.confirm(`确认删除账号「${account.name}」？此操作不会删除历史任务。`, '删除账号', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
  await run(() => deleteAccount(account.name).then(() => undefined), '账号已删除')
}

onMounted(refresh)
</script>

<template>
  <div class="page-stack">
    <section class="page-hero">
      <div>
        <p class="eyebrow">管理下载账号</p>
        <h2>账号池</h2>
      </div>
    </section>

    <el-card shadow="never">
      <template #header>
        <div class="card-header account-list-header">
          <div>
            <strong>账号列表</strong>
          </div>
          <AccountEditor :loading="loading" @phone-login="handlePhoneLogin" @import="handleImport" />
        </div>
      </template>
      <el-skeleton v-if="loading && !accounts.length" :rows="5" animated />
      <EmptyState
        v-else-if="!accounts.length"
        title="还没有账号"
        description="点击右上角添加账号：手机号登录或凭据导入。"
      />
      <AccountTable v-else :accounts="accounts" @verify="handleVerify" @enabled="handleEnabled" @delete="handleDelete" />
    </el-card>
  </div>
</template>
