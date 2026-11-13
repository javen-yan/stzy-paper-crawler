<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Connection, Cpu, Document, Files, Operation, Refresh } from '@element-plus/icons-vue'
import AboutUpdatePanel from '../components/settings/AboutUpdatePanel.vue'
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
const { loadRuntime } = useRuntime()
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
    await loadRuntime().catch(() => {})
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
        <h2>系统设置</h2>
        <p class="hero-subtitle">配置保存位置、网络代理、并发线程与文档转换环境。</p>
      </div>
    </section>

    <el-skeleton v-if="loading" :rows="8" animated />
    <template v-else>
      <el-card shadow="never" class="settings-tabs-card">
        <el-tabs v-model="activeTab" class="settings-tabs">
          <el-tab-pane name="basic">
            <template #label>
              <span class="tab-label"><el-icon><Operation /></el-icon>基础设置</span>
            </template>
            <BasicSettingsForm :settings="settings" :saving="saving" @save="save" />
          </el-tab-pane>

          <el-tab-pane name="proxy">
            <template #label>
              <span class="tab-label"><el-icon><Connection /></el-icon>网络代理</span>
            </template>
            <ProxySettingsForm :settings="settings" :saving="saving" @save="save" />
          </el-tab-pane>

          <el-tab-pane name="concurrency">
            <template #label>
              <span class="tab-label"><el-icon><Cpu /></el-icon>并发限制</span>
            </template>
            <ConcurrencySettingsForm :settings="settings" :saving="saving" @save="save" />
          </el-tab-pane>

          <el-tab-pane name="preview">
            <template #label>
              <span class="tab-label"><el-icon><Files /></el-icon>预览与超时</span>
            </template>
            <PreviewSettingsForm :settings="settings" :saving="saving" @save="save" />
          </el-tab-pane>

          <el-tab-pane name="fonts">
            <template #label>
              <span class="tab-label"><el-icon><Document /></el-icon>转换核心与字体</span>
            </template>
            <FontSettingsForm />
          </el-tab-pane>

          <el-tab-pane name="about">
            <template #label>
              <span class="tab-label"><el-icon><Refresh /></el-icon>软件更新</span>
            </template>
            <AboutUpdatePanel />
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>
  </div>
</template>
