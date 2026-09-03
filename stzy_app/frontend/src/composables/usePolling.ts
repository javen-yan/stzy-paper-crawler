import { onBeforeUnmount } from 'vue'

export function usePolling(work: () => void | Promise<void>, intervalMs = 1000, options: { hiddenIntervalMs?: number } = {}) {
  let timer: number | undefined
  let busy = false

  async function tick() {
    if (busy) return
    busy = true
    try {
      await work()
    } finally {
      busy = false
    }
  }

  function start() {
    stop()
    timer = window.setInterval(tick, document.hidden ? options.hiddenIntervalMs || intervalMs : intervalMs)
  }

  function stop() {
    if (timer) window.clearInterval(timer)
    timer = undefined
  }

  function restartForVisibility() {
    if (!timer) return
    start()
  }

  document.addEventListener('visibilitychange', restartForVisibility)

  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', restartForVisibility)
    stop()
  })

  return { start, stop, tick }
}
