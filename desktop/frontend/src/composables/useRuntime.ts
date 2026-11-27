import { computed, readonly, ref } from 'vue'
import { fetchRuntime } from '../api/runtime'
import type { RuntimeInfo } from '../types/runtime'

const runtime = ref<RuntimeInfo | null>(null)
const officeDialogDismissed = ref(false)

export function useRuntime() {
  async function loadRuntime() {
    runtime.value = await fetchRuntime()
    return runtime.value
  }

  function dismissOfficeDialog() {
    officeDialogDismissed.value = true
  }

  function openOfficeDialog() {
    officeDialogDismissed.value = false
  }

  return {
    runtime: readonly(runtime),
    officeDialogDismissed: readonly(officeDialogDismissed),
    isGui: computed(() => runtime.value?.mode === 'gui'),
    canUseLocal: computed(() => Boolean(runtime.value?.capabilities?.local_file_actions)),
    hasOfficeCore: computed(() => Boolean(runtime.value?.capabilities?.office_converter_detected)),
    officeEngineLabel: computed(() => runtime.value?.office_engine || ''),
    libreOfficeUrl: computed(() => runtime.value?.libreoffice_url || 'https://www.libreoffice.org/download/'),
    outputDir: computed(() => runtime.value?.output_dir || ''),
    loadRuntime,
    dismissOfficeDialog,
    openOfficeDialog,
  }
}
