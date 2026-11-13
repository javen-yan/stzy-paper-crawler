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
    loadRuntime,
  }
}
