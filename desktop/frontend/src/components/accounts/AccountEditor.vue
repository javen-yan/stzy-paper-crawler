<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CopyDocument, Key, Plus, Phone } from '@element-plus/icons-vue'
import { fetchAuthScript } from '../../api/accounts'
import { useToast } from '../../composables/useToast'
import type { AccountImportPayload, PhoneLoginPayload } from '../../types/accounts'

defineProps<{ loading?: boolean }>()
const emit = defineEmits<{
  phoneLogin: [payload: PhoneLoginPayload]
  import: [payload: AccountImportPayload]
}>()

const toast = useToast()
const visible = ref(false)
const activeTab = ref('phone')
const activeGuide = ref<string[]>([])
const authScript = ref('')
const scriptLoading = ref(false)

const phoneForm = ref({
  name: '',
  phone: '',
  password: '',
})
const credentialForm = ref({
  name: '',
  raw: '',
})

const canPhoneLogin = computed(() => Boolean(phoneForm.value.phone.trim()))
const canImport = computed(() => Boolean(credentialForm.value.raw.trim()))

watch([visible, activeTab], async ([isVisible, tab]) => {
  if (!isVisible || tab !== 'credential' || authScript.value || scriptLoading.value) return
  scriptLoading.value = true
  try {
    authScript.value = (await fetchAuthScript()).script
  } catch (error) {
    toast.error(error, '自动获取脚本加载失败')
  } finally {
    scriptLoading.value = false
  }
})

function reset() {
  phoneForm.value = { name: '', phone: '', password: '' }
  credentialForm.value = { name: '', raw: '' }
  activeTab.value = 'phone'
  activeGuide.value = []
}

function close() {
  visible.value = false
}

function submitPhoneLogin() {
  if (!canPhoneLogin.value) return
  emit('phoneLogin', {
    name: phoneForm.value.name.trim() || undefined,
    phone: phoneForm.value.phone.trim(),
    password: phoneForm.value.password || undefined,
  })
  close()
  reset()
}

function submitCredentialImport() {
  if (!canImport.value) return
  emit('import', {
    name: credentialForm.value.name.trim() || undefined,
    raw: credentialForm.value.raw.trim(),
  })
  close()
  reset()
}

async function copyScript() {
  if (!authScript.value) return
  try {
    await navigator.clipboard.writeText(authScript.value)
    toast.success('自动获取脚本已复制')
  } catch {
    toast.error('浏览器不允许自动复制，请手动选中脚本复制')
  }
}
</script>

<template>
  <el-button type="primary" :icon="Plus" @click="visible = true">添加账号</el-button>

  <el-dialog
    v-model="visible"
    title="添加账号"
    width="min(760px, 96vw)"
    class="account-dialog"
    destroy-on-close
  >
    <el-tabs v-model="activeTab" class="account-dialog-tabs">
      <el-tab-pane name="phone">
        <template #label>
          <span class="tab-label"><el-icon><Phone /></el-icon>手机号登录</span>
        </template>

        <div class="account-method-panel">
          <div class="method-title">
            <el-icon><Phone /></el-icon>
            <div>
              <strong>手机号登录</strong>
              <span>密码不填时，默认使用手机号后六位。</span>
            </div>
          </div>

          <el-form label-position="top" @submit.prevent="submitPhoneLogin">
            <el-form-item label="账号名称">
              <el-input v-model="phoneForm.name" placeholder="可选，例如：主账号 / 备用账号 1" clearable />
            </el-form-item>
            <el-form-item label="手机号" required>
              <el-input v-model="phoneForm.phone" inputmode="tel" placeholder="请输入手机号" clearable />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="phoneForm.password" type="password" show-password placeholder="不填则默认手机号后六位" />
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <el-tab-pane name="credential">
        <template #label>
          <span class="tab-label"><el-icon><Key /></el-icon>高级凭据</span>
        </template>

        <div class="stack">
          <el-alert
            title="可粘贴 fetch、cURL、Cookie、Token 或脚本输出，系统自动识别。"
            type="info"
            show-icon
            :closable="false"
          />

          <div class="credential-quick-guide">
            <div>
              <strong>如何获取凭据</strong>
            </div>
            <ol>
              <li>开发者工具 Network 复制 `user/detail` 的 fetch 或 cURL。</li>
              <li>Console 运行自动获取脚本。</li>
              <li>直接粘贴 Cookie 或 Token。</li>
            </ol>
          </div>

          <el-collapse v-model="activeGuide" class="compact-guide-collapse">
            <el-collapse-item name="script">
              <template #title>
                <span class="collapse-title">查看 / 复制 Console 自动获取脚本</span>
              </template>
              <div class="script-toolbar">
                <el-button size="small" :icon="CopyDocument" :loading="scriptLoading" @click.stop="copyScript">复制脚本</el-button>
                <span class="form-helper">登录官网后，在 Console 粘贴运行。</span>
              </div>
              <el-input
                v-model="authScript"
                type="textarea"
                :rows="4"
                readonly
                spellcheck="false"
                placeholder="正在加载自动获取脚本..."
              />
            </el-collapse-item>
          </el-collapse>

          <el-form label-position="top" @submit.prevent="submitCredentialImport">
            <el-form-item label="账号名称">
              <el-input v-model="credentialForm.name" placeholder="可选，不填则从 Token 里自动识别" clearable />
            </el-form-item>
            <el-form-item label="凭据内容" required>
              <el-input
                v-model="credentialForm.raw"
                type="textarea"
                :rows="5"
                spellcheck="false"
                placeholder="粘贴自动脚本输出、fetch、cURL、Cookie 或 Token"
              />
              <p class="form-helper">敏感信息会加密保存，列表中不明文展示。</p>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button
        v-if="activeTab === 'phone'"
        type="primary"
        :loading="loading"
        :disabled="!canPhoneLogin"
        @click="submitPhoneLogin"
      >
        登录并保存
      </el-button>
      <el-button
        v-else
        type="primary"
        :loading="loading"
        :disabled="!canImport"
        @click="submitCredentialImport"
      >
        导入并保存
      </el-button>
    </template>
  </el-dialog>
</template>
