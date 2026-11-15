import { getTodayUtcIso } from '../../../shared/lib/date'
import type { ObservationGranularity } from '../../../shared/types/geospatial'

export const MS_PER_DAY = 86_400_000

export function dateToUtcMs(isoDate: string): number {
  const parsed = Date.parse(`${isoDate}T00:00:00Z`)
  return Number.isNaN(parsed) ? Date.parse(`${getTodayUtcIso()}T00:00:00Z`) : parsed
}

export function stepIsoDate(
  isoDate: string,
  cadence: ObservationGranularity,
  dir: 1 | -1,
): string {
  const parsed = new Date(`${isoDate}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return isoDate
  if (cadence === 'daily' || cadence === '30-minute') {
    parsed.setUTCDate(parsed.getUTCDate() + dir)
  } else if (cadence === '8-day') {
    parsed.setUTCDate(parsed.getUTCDate() + 8 * dir)
  } else if (cadence === '16-day') {
    parsed.setUTCDate(parsed.getUTCDate() + 16 * dir)
  } else if (cadence === 'multi-year') {
    parsed.setUTCFullYear(parsed.getUTCFullYear() + dir)
  } else {
    parsed.setUTCMonth(parsed.getUTCMonth() + dir)
  }
  return parsed.toISOString().slice(0, 10)
}

export function dayIndexToIsoDate(rangeMinMs: number, dayIndex: number): string {
  return new Date(rangeMinMs + dayIndex * MS_PER_DAY).toISOString().slice(0, 10)
}

export function stepTimelineDate(params: {
  currentDate: string
  cadence: ObservationGranularity
  direction: 1 | -1
  minDate: string
  maxDate: string
}): string {
  const stepped = stepIsoDate(params.currentDate, params.cadence, params.direction)
  if (stepped < params.minDate) return params.minDate
  if (stepped > params.maxDate) return params.maxDate
  return stepped
}

export function computeTimelineSliderState(params: {
  dateRangeStart: string
  dateRangeEnd: string
  displayDate: string
  maxSelectableDate: string
}) {
  const cappedDisplay =
    params.displayDate > params.maxSelectableDate ? params.maxSelectableDate : params.displayDate
  const effectiveRangeEnd =
    cappedDisplay > params.dateRangeEnd ? cappedDisplay : params.dateRangeEnd
  const rangeMinMs = dateToUtcMs(params.dateRangeStart)
  const rangeMaxMs = Math.max(rangeMinMs + MS_PER_DAY, dateToUtcMs(effectiveRangeEnd))
  const totalDays = Math.max(1, Math.round((rangeMaxMs - rangeMinMs) / MS_PER_DAY))
  const clampedMs = Math.min(rangeMaxMs, Math.max(rangeMinMs, dateToUtcMs(params.displayDate)))
  const value = Math.min(
    totalDays,
    Math.max(0, Math.round((clampedMs - rangeMinMs) / MS_PER_DAY)),
  )
  return {
    min: 0,
    max: totalDays,
    value,
    totalDays,
    rangeMinMs,
    effectiveRangeEnd,
  }
}
