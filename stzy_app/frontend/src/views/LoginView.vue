<script setup lang="ts">
import { ref } from 'vue'
import { LockKeyhole, ShieldCheck } from 'lucide-vue-next'
import { useAuth } from '../composables/useAuth'
import { useRuntime } from '../composables/useRuntime'
import { useToast } from '../composables/useToast'

const password = ref('')
const loading = ref(false)
const { login } = useAuth()
const { runtime } = useRuntime()
const toast = useToast()

async function submit() {
  loading.value = true
  try {
    await login(password.value)
  } catch (error) {
    toast.error(error, '登录失败，请检查管理员密码')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-card class="login-card" shadow="never">
    <div class="login-brand">
      <el-icon :size="34"><ShieldCheck /></el-icon>
      <div>
        <h1>试卷下载器</h1>
        <p>{{ runtime?.mode === 'server' ? '管理员登录' : '本地 GUI 会话' }}</p>
      </div>
    </div>

    <el-alert
      v-if="runtime?.mode === 'gui'"
      title="GUI 模式通常会自动登录；如果停留在这里，请从启动器重新打开。"
      type="info"
      :closable="false"
      show-icon
    />

    <el-form v-else label-position="top" class="stack" @submit.prevent="submit">
      <el-form-item label="管理员密码" required>
        <el-input
          v-model="password"
          type="password"
          autocomplete="current-password"
          show-password
          placeholder="请输入管理员密码"
          :prefix-icon="LockKeyhole"
          @keyup.enter="submit"
        />
      </el-form-item>
      <el-button type="primary" size="large" class="full-width" :loading="loading" @click="submit">登录</el-button>
    </el-form>
  </el-card>
</template>
