import { computed, readonly, ref } from 'vue'
import { fetchRuntime } from '../api/runtime'
import type { RuntimeInfo } from '../types/runtime'

const runtime = ref<RuntimeInfo | null>(null)

export function useRuntime() {
  async function loadRuntime() {
    runtime.value = await fetchRuntime()
    return runtime.value
  }

  return {
    runtime: readonly(runtime),
    isGui: computed(() => runtime.value?.mode === 'gui'),
    canUseLocal: computed(() => Boolean(runtime.value?.capabilities?.local_file_actions)),
    hasOfficeCore: computed(() => Boolean(runtime.value?.capabilities?.office_converter_detected)),
    officeEngineLabel: computed(() => runtime.value?.office_engine || ''),
    libreOfficeUrl: computed(() => runtime.value?.libreoffice_url || 'https://www.libreoffice.org/download/'),
    outputDir: computed(() => runtime.value?.output_dir || ''),
    loadRuntime,
  }
}
