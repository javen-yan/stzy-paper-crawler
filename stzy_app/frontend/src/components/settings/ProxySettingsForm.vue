<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Link } from '@element-plus/icons-vue'
import { bindLocalProxyIp } from '../../api/proxy'
import { useToast } from '../../composables/useToast'
import type { PublicSettings } from '../../types/settings'

const props = defineProps<{ settings: PublicSettings; saving?: boolean }>()
const emit = defineEmits<{ save: [payload: Partial<PublicSettings>] }>()
const toast = useToast()

type ProxyMode = 'off' | 'fixed' | 'api'
type ProxyProvider = 'generic' | 'shenlong'

const redactedValue = '***'
const binding = ref(false)
const bindResult = ref('')

const form = reactive({
  proxy_mode: 'off' as ProxyMode,
  proxy_provider: 'generic' as ProxyProvider,
  proxy_pool: '',
  proxy_api_url: '',
  concurrency: 1,
  proxy_max_failures: 3,
  proxy_cooldown_seconds: 300,
  proxy_min_ttl_seconds: 30,
  shenlong_whitelist_key: '',
  shenlong_whitelist_sign: '',
  has_proxy_pool: false,
  has_proxy_api_url: false,
  has_shenlong_whitelist_key: false,
  has_shenlong_whitelist_sign: false,
})

const modeDescription = computed(() => {
  if (form.proxy_mode === 'off') return '任务直接访问目标站点，不使用代理。'
  if (form.proxy_mode === 'fixed') return '从固定代理池轮换，失败后自动切换。'
  return '按接口提取代理，失败自动切换与重试。'
})

function visibleSecret(value: unknown) {
  return value === redactedValue ? '' : String(value || '')
}

function hasSavedSecret(value: unknown) {
  return Boolean(value)
}

watch(
  () => props.settings,
  (settings) => {
    const mode = String(settings.proxy_mode || 'off')
    const provider = String(settings.proxy_provider || 'generic')
    form.proxy_mode = (['off', 'fixed', 'api'].includes(mode) ? mode : 'off') as ProxyMode
    form.proxy_provider = (['generic', 'shenlong'].includes(provider) ? provider : 'generic') as ProxyProvider
    form.proxy_pool = visibleSecret(settings.proxy_pool)
    form.proxy_api_url = visibleSecret(settings.proxy_api_url)
    form.concurrency = Number(settings.concurrency || 1)
    form.proxy_max_failures = Number(settings.proxy_max_failures || 3)
    form.proxy_cooldown_seconds = Number(settings.proxy_cooldown_seconds || 300)
    form.proxy_min_ttl_seconds = Number(settings.proxy_min_ttl_seconds || 30)
    form.shenlong_whitelist_key = visibleSecret(settings.shenlong_whitelist_key)
    form.shenlong_whitelist_sign = visibleSecret(settings.shenlong_whitelist_sign)
    form.has_proxy_pool = hasSavedSecret(settings.proxy_pool)
    form.has_proxy_api_url = hasSavedSecret(settings.proxy_api_url)
    form.has_shenlong_whitelist_key = hasSavedSecret(settings.shenlong_whitelist_key)
    form.has_shenlong_whitelist_sign = hasSavedSecret(settings.shenlong_whitelist_sign)
  },
  { immediate: true },
)

function buildPayload() {
  const payload: Partial<PublicSettings> = {
    proxy_mode: form.proxy_mode,
    proxy_provider: form.proxy_provider,
    concurrency: form.concurrency,
    proxy_max_failures: form.proxy_max_failures,
    proxy_cooldown_seconds: form.proxy_cooldown_seconds,
    proxy_min_ttl_seconds: form.proxy_min_ttl_seconds,
  }

  if (form.proxy_mode === 'fixed' && form.proxy_pool.trim()) {
    payload.proxy_pool = form.proxy_pool.trim()
  }

  if (form.proxy_mode === 'api' && form.proxy_api_url.trim()) {
    payload.proxy_api_url = form.proxy_api_url.trim()
  }

  if (form.proxy_mode === 'api' && form.proxy_provider === 'shenlong') {
    if (form.shenlong_whitelist_key.trim()) payload.shenlong_whitelist_key = form.shenlong_whitelist_key.trim()
    if (form.shenlong_whitelist_sign.trim()) payload.shenlong_whitelist_sign = form.shenlong_whitelist_sign.trim()
  }

  return payload
}

function submit() {
  emit('save', buildPayload())
}

async function bindLocalIp() {
  binding.value = true
  bindResult.value = ''
  try {
    const result = await bindLocalProxyIp()
    bindResult.value = result.message || (result.ip ? `本机 IP 已绑定：${result.ip}` : '绑定完成')
    toast.success(bindResult.value)
  } catch (error) {
    toast.error(error, '神龙白名单绑定失败')
  } finally {
    binding.value = false
  }
}
</script>

<template>
  <el-card shadow="never" class="proxy-settings-card">
    <template #header>
      <div class="card-header">
        <span>代理设置</span>
      </div>
    </template>

    <el-form label-position="top" class="settings-form">
      <el-form-item label="代理模式">
        <el-radio-group v-model="form.proxy_mode" class="proxy-mode-group">
          <el-radio-button label="off">不使用代理</el-radio-button>
          <el-radio-button label="fixed">固定代理池</el-radio-button>
          <el-radio-button label="api">API 提取代理</el-radio-button>
        </el-radio-group>
        <p class="form-helper">{{ modeDescription }}</p>
      </el-form-item>

      <template v-if="form.proxy_mode === 'fixed'">
        <el-form-item label="固定代理池">
          <el-input
            v-model="form.proxy_pool"
            type="textarea"
            :rows="5"
            placeholder="每行一个代理，例如：http://user:pass@host:port"
          />
          <p class="form-helper">
            <span v-if="form.has_proxy_pool && !form.proxy_pool">已保存代理池；重新输入后会覆盖。</span>
            <span v-else>每行一个代理。</span>
          </p>
        </el-form-item>
      </template>

      <template v-if="form.proxy_mode === 'api'">
        <el-form-item label="代理服务商">
          <el-select v-model="form.proxy_provider" class="full-width">
            <el-option label="通用提取接口" value="generic" />
            <el-option label="神龙HTTP" value="shenlong" />
          </el-select>
        </el-form-item>

        <el-form-item label="代理提取 API">
          <el-input
            v-model="form.proxy_api_url"
            placeholder="填写代理提取接口，任务运行时后台自动拉取"
            clearable
          />
          <p class="form-helper">
            <span v-if="form.has_proxy_api_url && !form.proxy_api_url">已保存提取接口；重新输入后会覆盖。</span>
            <span v-else>填写代理提取接口地址。</span>
          </p>
        </el-form-item>

        <el-form-item label="代理拉取数量 / 开启客户端数量">
          <el-input-number v-model="form.concurrency" :min="1" :max="20" />
          <p class="form-helper">
            这个值只控制代理 API 一次维持多少个可用出口，也就是开启客户端数量；不控制试卷下载线程。
          </p>
        </el-form-item>

        <el-alert
          v-if="form.proxy_provider === 'shenlong'"
          title="神龙HTTP配置"
          description="开通白名单后，填写 Key 和 Sign。已保存的敏感值不会明文回显。"
          type="warning"
          show-icon
          :closable="false"
        />

        <div v-if="form.proxy_provider === 'shenlong'" class="shenlong-grid">
          <el-form-item label="神龙白名单 Key">
            <el-input
              v-model="form.shenlong_whitelist_key"
              placeholder="已保存时留空即可；重新输入则覆盖"
              show-password
              clearable
            />
            <p v-if="form.has_shenlong_whitelist_key && !form.shenlong_whitelist_key" class="form-helper">已保存 Key，不明文显示。</p>
          </el-form-item>

          <el-form-item label="神龙白名单 Sign">
            <el-input
              v-model="form.shenlong_whitelist_sign"
              placeholder="已保存时留空即可；重新输入则覆盖"
              show-password
              clearable
            />
            <p v-if="form.has_shenlong_whitelist_sign && !form.shenlong_whitelist_sign" class="form-helper">已保存 Sign，不明文显示。</p>
          </el-form-item>
        </div>
        <div v-if="form.proxy_provider === 'shenlong'" class="bind-ip-panel">
          <div>
            <strong>白名单绑定</strong>
            <p v-if="bindResult" class="form-helper">{{ bindResult }}</p>
          </div>
          <el-button :icon="Link" :loading="binding" @click="bindLocalIp">绑定本机 IP</el-button>
        </div>
      </template>

      <el-divider content-position="left">失败处理</el-divider>
      <div class="shenlong-grid">
        <el-form-item label="代理失败次数阈值">
          <el-input-number v-model="form.proxy_max_failures" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="失败冷却秒数">
          <el-input-number v-model="form.proxy_cooldown_seconds" :min="10" :max="3600" :step="10" />
        </el-form-item>
        <el-form-item v-if="form.proxy_mode === 'api'" label="最小剩余有效秒数">
          <el-input-number v-model="form.proxy_min_ttl_seconds" :min="0" :max="300" :step="10" />
          <p class="form-helper">代理有效期不足这个值时不再下发，直接提前换新。</p>
        </el-form-item>
      </div>

      <el-button type="primary" :loading="saving" @click="submit">保存代理策略</el-button>
    </el-form>
  </el-card>
</template>
