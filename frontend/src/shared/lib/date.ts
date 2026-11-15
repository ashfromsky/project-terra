export function getTodayUtcIso(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10)
}

export function getLocalTodayIso(now: Date = new Date()): string {
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function getMaxSelectableDateIso(now: Date = new Date()): string {
  const utc = getTodayUtcIso(now)
  const local = getLocalTodayIso(now)
  return local > utc ? local : utc
}
