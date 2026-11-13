<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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

const usableCount = computed(() => accounts.value.filter((a) => a.enabled && a.usable).length)
const vipCount = computed(() =>
  accounts.value.filter((a) => String(a.account_type_label || '').toUpperCase().includes('VIP') || Number(a.surplus_num || 0) > 0).length,
)

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
    await refresh().catch(() => {})
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
  await ElMessageBox.confirm(`确认删除账号「${account.name}」？此操作不会删除已下载文件。`, '删除账号', {
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
        <h2>账号管理</h2>
        <p class="hero-subtitle">添加官网登录账号，下载任务会自动按可用状态与剩余次数轮换使用。</p>
      </div>
      <div class="hero-actions">
        <AccountEditor :loading="loading" @phone-login="handlePhoneLogin" @import="handleImport" />
      </div>
    </section>

    <el-card shadow="never">
      <template #header>
        <div class="card-header account-list-header">
          <div class="account-header-meta">
            <strong>已添加账号</strong>
            <span class="meta-pill">共 {{ accounts.length }} 个</span>
            <span class="meta-pill success">可用 {{ usableCount }}</span>
            <span v-if="vipCount > 0" class="meta-pill accent">VIP / 有额度 {{ vipCount }}</span>
          </div>
        </div>
      </template>
      <el-skeleton v-if="loading && !accounts.length" :rows="5" animated />
      <EmptyState
        v-else-if="!accounts.length"
        title="暂未添加账号"
        description="点击右上角「添加账号」，可使用手机号登录或导入浏览器凭据。"
      />
      <AccountTable v-else :accounts="accounts" @verify="handleVerify" @enabled="handleEnabled" @delete="handleDelete" />
    </el-card>
  </div>
</template>

<style scoped>
.account-header-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-pill {
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 24px;
  color: var(--app-muted);
  background: rgba(148, 163, 184, 0.1);
  border: 1px solid var(--app-border);
}

.meta-pill.success {
  color: var(--app-accent);
  background: var(--app-accent-soft);
  border-color: rgba(52, 211, 153, 0.28);
}

.meta-pill.accent {
  color: #a5b4fc;
  background: var(--app-primary-soft);
  border-color: rgba(129, 140, 248, 0.3);
}
</style>
