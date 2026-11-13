import { computed, readonly, ref } from 'vue'

const activeTaskId = ref('')
const footerExpanded = ref(false)
const footerHeight = ref(220)
const logAutoScroll = ref(true)

export function useLayoutState() {
  function setActiveTaskId(taskId: string) {
    activeTaskId.value = taskId
  }

  function toggleFooter() {
    footerExpanded.value = !footerExpanded.value
  }

  function setFooterExpanded(value: boolean) {
    footerExpanded.value = value
  }

  function setFooterHeight(value: number) {
    footerHeight.value = Math.max(120, Math.min(value, Math.floor(window.innerHeight * 0.5)))
  }

  function setLogAutoScroll(value: boolean) {
    logAutoScroll.value = value
  }

  return {
    activeTaskId: readonly(activeTaskId),
    footerExpanded: readonly(footerExpanded),
    footerHeight: readonly(footerHeight),
    logAutoScroll: readonly(logAutoScroll),
    contentFooterOffset: computed(() => (footerExpanded.value ? footerHeight.value : 44)),
    setActiveTaskId,
    toggleFooter,
    setFooterExpanded,
    setFooterHeight,
    setLogAutoScroll,
  }
}
