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
type SecretKey = 'proxy_pool' | 'proxy_api_url' | 'shenlong_whitelist_key' | 'shenlong_whitelist_sign'

const binding = ref(false)
const bindResult = ref('')

const initialMasked = reactive<Record<SecretKey, string>>({
  proxy_pool: '',
  proxy_api_url: '',
  shenlong_whitelist_key: '',
  shenlong_whitelist_sign: '',
})

const editingSecret = reactive<Record<SecretKey, boolean>>({
  proxy_pool: false,
  proxy_api_url: false,
  shenlong_whitelist_key: false,
  shenlong_whitelist_sign: false,
})

const clearedSecret = reactive<Record<SecretKey, boolean>>({
  proxy_pool: false,
  proxy_api_url: false,
  shenlong_whitelist_key: false,
  shenlong_whitelist_sign: false,
})

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
  proxy_pool_count: 0,
})

const modeDescription = computed(() => {
  if (form.proxy_mode === 'off') return '直连目标站点，不使用代理。'
  if (form.proxy_mode === 'fixed') return '从固定列表中轮换代理，异常节点自动冷却。'
  return '任务运行时从提取接口拉取代理 IP，到期或失败自动换新。'
})

function syncSecretField(key: SecretKey, rawValue: unknown, hasFlag: unknown) {
  const str = String(rawValue || '')
  const configured = Boolean(hasFlag || str)
  const display = configured ? (str === '***' ? '*****' : str) : ''
  initialMasked[key] = display
  form[key] = display
  editingSecret[key] = !configured
  clearedSecret[key] = false
  return configured
}

watch(
  () => props.settings,
  (settings) => {
    const mode = String(settings.proxy_mode || 'off')
    const provider = String(settings.proxy_provider || 'generic')
    form.proxy_mode = (['off', 'fixed', 'api'].includes(mode) ? mode : 'off') as ProxyMode
    form.proxy_provider = (['generic', 'shenlong'].includes(provider) ? provider : 'generic') as ProxyProvider
    form.concurrency = Number(settings.concurrency || 1)
    form.proxy_max_failures = Number(settings.proxy_max_failures || 3)
    form.proxy_cooldown_seconds = Number(settings.proxy_cooldown_seconds || 300)
    form.proxy_min_ttl_seconds = Number(settings.proxy_min_ttl_seconds || 30)
    form.proxy_pool_count = Number(settings.proxy_pool_count || 0)

    form.has_proxy_pool = syncSecretField('proxy_pool', settings.proxy_pool, settings.has_proxy_pool)
    form.has_proxy_api_url = syncSecretField('proxy_api_url', settings.proxy_api_url, settings.has_proxy_api_url)
    form.has_shenlong_whitelist_key = syncSecretField(
      'shenlong_whitelist_key',
      settings.shenlong_whitelist_key,
      settings.has_shenlong_whitelist_key,
    )
    form.has_shenlong_whitelist_sign = syncSecretField(
      'shenlong_whitelist_sign',
      settings.shenlong_whitelist_sign,
      settings.has_shenlong_whitelist_sign,
    )
  },
  { immediate: true },
)

function startEditSecret(key: SecretKey) {
  editingSecret[key] = true
  clearedSecret[key] = false
  form[key] = ''
}

function cancelEditSecret(key: SecretKey) {
  editingSecret[key] = false
  clearedSecret[key] = false
  form[key] = initialMasked[key]
}

function markClearSecret(key: SecretKey) {
  editingSecret[key] = true
  clearedSecret[key] = true
  form[key] = ''
}

function attachSecretToPayload(payload: Partial<PublicSettings>, key: SecretKey) {
  const val = form[key].trim()
  if (clearedSecret[key] && !val) {
    payload[key] = ''
    return
  }
  if (!editingSecret[key]) {
    return
  }
  if (val && val !== initialMasked[key] && !val.includes('*****')) {
    payload[key] = val
  }
}

function buildPayload() {
  const payload: Partial<PublicSettings> = {
    proxy_mode: form.proxy_mode,
    proxy_provider: form.proxy_provider,
    concurrency: form.concurrency,
    proxy_max_failures: form.proxy_max_failures,
    proxy_cooldown_seconds: form.proxy_cooldown_seconds,
    proxy_min_ttl_seconds: form.proxy_min_ttl_seconds,
  }

  if (form.proxy_mode === 'fixed') {
    attachSecretToPayload(payload, 'proxy_pool')
  }

  if (form.proxy_mode === 'api') {
    attachSecretToPayload(payload, 'proxy_api_url')
    if (form.proxy_provider === 'shenlong') {
      attachSecretToPayload(payload, 'shenlong_whitelist_key')
      attachSecretToPayload(payload, 'shenlong_whitelist_sign')
    }
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
    bindResult.value = result.message || (result.ip ? `本机 IP 已加入白名单：${result.ip}` : '绑定完成')
    toast.success(bindResult.value)
  } catch (error) {
    toast.error(error, '白名单绑定失败')
  } finally {
    binding.value = false
  }
}
</script>

<template>
  <el-card shadow="never" class="proxy-settings-card">
    <template #header>
      <div class="card-header">
        <span>网络代理配置</span>
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
        <el-form-item>
          <template #label>
            <div class="secret-label-row">
              <span>固定代理列表</span>
              <span v-if="form.has_proxy_pool && !clearedSecret.proxy_pool" class="saved-badge">
                已配置{{ form.proxy_pool_count ? `（${form.proxy_pool_count} 条）` : '' }}
              </span>
              <span v-else-if="clearedSecret.proxy_pool" class="cleared-badge">保存后清空</span>
              <div v-if="form.has_proxy_pool" class="secret-actions">
                <el-button v-if="!editingSecret.proxy_pool" link type="primary" size="small" @click="startEditSecret('proxy_pool')">
                  重新填写
                </el-button>
                <el-button v-else link size="small" @click="cancelEditSecret('proxy_pool')">恢复已存配置</el-button>
                <el-button v-if="!clearedSecret.proxy_pool" link type="danger" size="small" @click="markClearSecret('proxy_pool')">
                  清空
                </el-button>
              </div>
            </div>
          </template>
          <el-input
            v-model="form.proxy_pool"
            type="textarea"
            :rows="5"
            :readonly="!editingSecret.proxy_pool"
            class="mono-input"
            placeholder="每行一个代理，例如：http://user:pass@host:port 或 socks5://127.0.0.1:1080"
            @input="clearedSecret.proxy_pool = false"
          />
          <p class="form-helper">
            <span v-if="!editingSecret.proxy_pool">敏感账号密码已使用 ***** 脱敏展示；如需更换请点击「重新填写」。</span>
            <span v-else-if="clearedSecret.proxy_pool">点击下方「保存代理配置」后将清空已保存的代理列表。</span>
            <span v-else>每行填写一条代理地址。</span>
          </p>
        </el-form-item>
      </template>

      <template v-if="form.proxy_mode === 'api'">
        <el-form-item label="服务商类型">
          <el-select v-model="form.proxy_provider" class="full-width">
            <el-option label="通用 API 提取接口" value="generic" />
            <el-option label="神龙 HTTP（支持自动绑定本机白名单）" value="shenlong" />
          </el-select>
        </el-form-item>

        <el-form-item>
          <template #label>
            <div class="secret-label-row">
              <span>代理提取 API 地址</span>
              <span v-if="form.has_proxy_api_url && !clearedSecret.proxy_api_url" class="saved-badge">已配置</span>
              <span v-else-if="clearedSecret.proxy_api_url" class="cleared-badge">保存后清空</span>
              <div v-if="form.has_proxy_api_url" class="secret-actions">
                <el-button v-if="!editingSecret.proxy_api_url" link type="primary" size="small" @click="startEditSecret('proxy_api_url')">
                  修改地址
                </el-button>
                <el-button v-else link size="small" @click="cancelEditSecret('proxy_api_url')">取消修改</el-button>
                <el-button v-if="!clearedSecret.proxy_api_url" link type="danger" size="small" @click="markClearSecret('proxy_api_url')">
                  清空
                </el-button>
              </div>
            </div>
          </template>
          <el-input
            v-model="form.proxy_api_url"
            :readonly="!editingSecret.proxy_api_url"
            class="mono-input"
            placeholder="粘贴完整的提取链接（例如 https://...）"
            clearable
            @input="clearedSecret.proxy_api_url = false"
          />
          <p class="form-helper">
            <span v-if="!editingSecret.proxy_api_url">接口中的密钥参数已用 ***** 脱敏显示；如需更换请点击右侧「修改地址」。</span>
            <span v-else-if="clearedSecret.proxy_api_url">点击「保存代理配置」后将清空提取接口。</span>
            <span v-else>任务启动后会自动按需调用该接口获取代理 IP。</span>
          </p>
        </el-form-item>

        <el-form-item label="同时维持代理出口数">
          <el-input-number v-model="form.concurrency" :min="1" :max="20" />
          <p class="form-helper">控制代理池同时保持多少个可用代理出口。</p>
        </el-form-item>

        <div v-if="form.proxy_provider === 'shenlong'" class="shenlong-grid">
          <el-form-item>
            <template #label>
              <div class="secret-label-row">
                <span>白名单 Key</span>
                <span v-if="form.has_shenlong_whitelist_key && !clearedSecret.shenlong_whitelist_key" class="saved-badge">已配置</span>
                <span v-else-if="clearedSecret.shenlong_whitelist_key" class="cleared-badge">保存后清空</span>
                <div v-if="form.has_shenlong_whitelist_key" class="secret-actions">
                  <el-button
                    v-if="!editingSecret.shenlong_whitelist_key"
                    link
                    type="primary"
                    size="small"
                    @click="startEditSecret('shenlong_whitelist_key')"
                  >
                    修改
                  </el-button>
                  <el-button v-else link size="small" @click="cancelEditSecret('shenlong_whitelist_key')">取消</el-button>
                  <el-button
                    v-if="!clearedSecret.shenlong_whitelist_key"
                    link
                    type="danger"
                    size="small"
                    @click="markClearSecret('shenlong_whitelist_key')"
                  >
                    清空
                  </el-button>
                </div>
              </div>
            </template>
            <el-input
              v-model="form.shenlong_whitelist_key"
              :readonly="!editingSecret.shenlong_whitelist_key"
              class="mono-input"
              placeholder="填写神龙白名单 Key"
              clearable
              @input="clearedSecret.shenlong_whitelist_key = false"
            />
          </el-form-item>

          <el-form-item>
            <template #label>
              <div class="secret-label-row">
                <span>白名单 Sign</span>
                <span v-if="form.has_shenlong_whitelist_sign && !clearedSecret.shenlong_whitelist_sign" class="saved-badge">已配置</span>
                <span v-else-if="clearedSecret.shenlong_whitelist_sign" class="cleared-badge">保存后清空</span>
                <div v-if="form.has_shenlong_whitelist_sign" class="secret-actions">
                  <el-button
                    v-if="!editingSecret.shenlong_whitelist_sign"
                    link
                    type="primary"
                    size="small"
                    @click="startEditSecret('shenlong_whitelist_sign')"
                  >
                    修改
                  </el-button>
                  <el-button v-else link size="small" @click="cancelEditSecret('shenlong_whitelist_sign')">取消</el-button>
                  <el-button
                    v-if="!clearedSecret.shenlong_whitelist_sign"
                    link
                    type="danger"
                    size="small"
                    @click="markClearSecret('shenlong_whitelist_sign')"
                  >
                    清空
                  </el-button>
                </div>
              </div>
            </template>
            <el-input
              v-model="form.shenlong_whitelist_sign"
              :readonly="!editingSecret.shenlong_whitelist_sign"
              class="mono-input"
              placeholder="填写神龙白名单 Sign"
              clearable
              @input="clearedSecret.shenlong_whitelist_sign = false"
            />
          </el-form-item>
        </div>

        <div v-if="form.proxy_provider === 'shenlong'" class="bind-ip-panel">
          <div>
            <strong>本机白名单绑定</strong>
            <p class="form-helper">{{ bindResult || '保存 Key 与 Sign 后，可一键将当前公网 IP 加入神龙白名单。' }}</p>
          </div>
          <el-button :icon="Link" :loading="binding" @click="bindLocalIp">绑定本机 IP</el-button>
        </div>
      </template>

      <el-divider content-position="left">容错与轮换参数</el-divider>
      <div class="shenlong-grid">
        <el-form-item label="单节点最大连续失败次数">
          <el-input-number v-model="form.proxy_max_failures" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="失败冷却时长（秒）">
          <el-input-number v-model="form.proxy_cooldown_seconds" :min="10" :max="3600" :step="10" />
        </el-form-item>
        <el-form-item v-if="form.proxy_mode === 'api'" label="最小剩余有效期（秒）">
          <el-input-number v-model="form.proxy_min_ttl_seconds" :min="0" :max="300" :step="10" />
          <p class="form-helper">剩余时间低于该阈值时提前换用新代理。</p>
        </el-form-item>
      </div>

      <el-button type="primary" :loading="saving" @click="submit">保存代理配置</el-button>
    </el-form>
  </el-card>
</template>

<style scoped>
.secret-label-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.saved-badge {
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 20px;
  color: var(--app-accent);
  background: var(--app-accent-soft);
  border: 1px solid rgba(52, 211, 153, 0.28);
}

.cleared-badge {
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 20px;
  color: var(--app-warning);
  background: rgba(245, 158, 11, 0.14);
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.secret-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.mono-input :deep(input),
.mono-input :deep(textarea) {
  font-family: var(--app-mono);
  font-size: 12.5px;
}
</style>
