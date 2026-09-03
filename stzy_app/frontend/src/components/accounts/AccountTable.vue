<script setup lang="ts">
import { CircleCheck, Delete } from '@element-plus/icons-vue'
import StatusTag from '../common/StatusTag.vue'
import type { Account } from '../../types/accounts'

defineProps<{ accounts: Account[] }>()
defineEmits<{
  verify: [account: Account]
  enabled: [account: Account, enabled: boolean]
  delete: [account: Account]
}>()

const importMethodText: Record<string, string> = {
  phone: '手机号',
  json: 'JSON',
  network_fetch: 'fetch',
  network_curl: 'cURL',
  token: 'Token',
  cookie: 'Cookie',
  manual: '手动',
}

function methodLabel(account: Account) {
  if (account.login_phone) return '手机号'
  return importMethodText[String(account.import_method || '')] || account.import_method || '手动'
}

function statusFor(account: Account) {
  if (!account.enabled) return { status: 'cancelled', label: '停用' }
  if (account.in_cooldown) return { status: 'paused', label: account.health_label || '冷却中' }
  if (account.usable) return { status: 'completed', label: account.health_label || '正常' }
  return { status: 'failed', label: account.health_label || '异常' }
}
</script>

<template>
  <el-table :data="accounts" empty-text="暂无账号" row-key="name">
    <el-table-column label="账号" min-width="190">
      <template #default="{ row }">
        <div class="account-cell">
          <strong>{{ row.name }}</strong>
          <small v-if="row.login_phone">{{ row.login_phone }}</small>
          <small v-else>高级凭据导入</small>
        </div>
      </template>
    </el-table-column>
    <el-table-column label="状态" width="150">
      <template #default="{ row }">
        <StatusTag :status="statusFor(row).status" :label="statusFor(row).label" />
      </template>
    </el-table-column>
    <el-table-column prop="account_type_label" label="账号类型" width="130" />
    <el-table-column label="导入方式" width="110">
      <template #default="{ row }">{{ methodLabel(row) }}</template>
    </el-table-column>
    <el-table-column label="剩余额度" width="110">
      <template #default="{ row }">{{ row.surplus_num ?? '-' }}</template>
    </el-table-column>
    <el-table-column label="最近验证" width="170">
      <template #default="{ row }">{{ row.last_checked_at || row.last_verified_at || '-' }}</template>
    </el-table-column>
    <el-table-column label="错误原因" min-width="180" show-overflow-tooltip>
      <template #default="{ row }">{{ row.last_error || row.error || '-' }}</template>
    </el-table-column>
    <el-table-column label="启用" width="82" align="center">
      <template #default="{ row }">
        <el-switch :model-value="row.enabled" @change="$emit('enabled', row, Boolean($event))" />
      </template>
    </el-table-column>
    <el-table-column label="操作" width="96" align="center" fixed="right">
      <template #default="{ row }">
        <div class="table-action-icons">
          <el-tooltip content="验证账号" placement="top" :show-after="250">
            <el-button
              class="table-icon-action"
              :icon="CircleCheck"
              circle
              size="small"
              aria-label="验证账号"
              @click="$emit('verify', row)"
            />
          </el-tooltip>
          <el-tooltip content="删除账号" placement="top" :show-after="250">
            <el-button
              class="table-icon-action danger"
              :icon="Delete"
              circle
              size="small"
              aria-label="删除账号"
              @click="$emit('delete', row)"
            />
          </el-tooltip>
        </div>
      </template>
    </el-table-column>
  </el-table>
</template>
