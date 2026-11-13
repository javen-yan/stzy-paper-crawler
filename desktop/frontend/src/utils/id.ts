function compactTimestamp(date = new Date()) {
  const pad = (value: number, size = 2) => String(value).padStart(size, '0')
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    '_',
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
    '_',
    pad(date.getMilliseconds(), 3),
  ].join('')
}

function randomSegment() {
  return Math.random().toString(36).slice(2, 10)
}

export function createClientId(prefix = 'id') {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID()
  }
  return `${prefix}_${compactTimestamp()}_${randomSegment()}`
}
