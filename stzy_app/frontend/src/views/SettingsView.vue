<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Connection, Cpu, Document, Files, Operation } from '@element-plus/icons-vue'
import BasicSettingsForm from '../components/settings/BasicSettingsForm.vue'
import ConcurrencySettingsForm from '../components/settings/ConcurrencySettingsForm.vue'
import FontSettingsForm from '../components/settings/FontSettingsForm.vue'
import PreviewSettingsForm from '../components/settings/PreviewSettingsForm.vue'
import ProxySettingsForm from '../components/settings/ProxySettingsForm.vue'
import { fetchSettings, updateSettings } from '../api/settings'
import { useRuntime } from '../composables/useRuntime'
import { useToast } from '../composables/useToast'
import type { PublicSettings } from '../types/settings'

const toast = useToast()
const { runtime, canUseLocal } = useRuntime()
const settings = ref<PublicSettings>({})
const loading = ref(false)
const saving = ref(false)
const activeTab = ref('basic')

async function refresh() {
  loading.value = true
  try {
    settings.value = await fetchSettings()
  } finally {
    loading.value = false
  }
}

async function save(payload: Partial<PublicSettings>) {
  saving.value = true
  try {
    settings.value = await updateSettings(payload)
    toast.success('设置已保存')
  } catch (error) {
    toast.error(error, '设置保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="page-stack">
    <section class="page-hero">
      <div>
        <p class="eyebrow">下载行为、代理与并发配置</p>
        <h2>设置</h2>
        <p>修改后立即生效，作用于后续新建任务。</p>
      </div>
      <el-tag size="large">{{ runtime?.mode === 'server' ? `${runtime.host}:${runtime.port}` : '本地 GUI 自动端口' }}</el-tag>
    </section>

    <el-alert
      v-if="runtime?.mode === 'server'"
      title="Server 模式：监听 0.0.0.0 端口；HTTPS、域名与反向代理由部署方配置。"
      type="info"
      show-icon
      :closable="false"
    />
    <el-alert
      v-else-if="canUseLocal"
      title="GUI 模式：支持本地目录选择与打开。"
      type="success"
      show-icon
      :closable="false"
    />

    <el-skeleton v-if="loading" :rows="8" animated />
    <template v-else>
      <el-card shadow="never" class="settings-tabs-card">
        <el-tabs v-model="activeTab" class="settings-tabs">
          <el-tab-pane name="basic">
            <template #label>
              <span class="tab-label"><el-icon><Operation /></el-icon>基础策略</span>
            </template>
            <BasicSettingsForm :settings="settings" :saving="saving" @save="save" />
          </el-tab-pane>

          <el-tab-pane name="proxy">
            <template #label>
              <span class="tab-label"><el-icon><Connection /></el-icon>代理策略</span>
            </template>
            <ProxySettingsForm :settings="settings" :saving="saving" @save="save" />
          </el-tab-pane>

          <el-tab-pane name="concurrency">
            <template #label>
              <span class="tab-label"><el-icon><Cpu /></el-icon>并发控制</span>
            </template>
            <ConcurrencySettingsForm :settings="settings" :saving="saving" @save="save" />
          </el-tab-pane>

          <el-tab-pane name="preview">
            <template #label>
              <span class="tab-label"><el-icon><Files /></el-icon>预览与转换</span>
            </template>
            <PreviewSettingsForm :settings="settings" :saving="saving" @save="save" />
          </el-tab-pane>

          <el-tab-pane name="fonts">
            <template #label>
              <span class="tab-label"><el-icon><Document /></el-icon>Word 字体</span>
            </template>
            <FontSettingsForm />
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>
  </div>
</template>
