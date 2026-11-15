import { afterEach, describe, expect, it, vi } from 'vitest'
import { BASEMAP_PROVIDER_REGISTRY, resolveGibsDate } from '../../config/geospatial'
import { getMaxSelectableDateIso, getTodayUtcIso } from '../date'

describe('dynamic date helpers', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('tracks the active calendar day across day boundaries', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-18T12:00:00Z'))
    expect(getTodayUtcIso()).toBe('2026-11-18')
    expect(getMaxSelectableDateIso()).toBe('2026-11-18')

    vi.setSystemTime(new Date('2027-01-03T12:00:00Z'))
    expect(getTodayUtcIso()).toBe('2027-01-03')
    expect(getMaxSelectableDateIso()).toBe('2027-01-03')
  })

  it('allows current-day GIBS dates without clamping to a stale 2026-11-02 cutoff', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-18T12:00:00Z'))
    const viirsConfig = BASEMAP_PROVIDER_REGISTRY['viirs-true-color']

    expect(resolveGibsDate('2026-11-18', viirsConfig)).toBe('2026-11-18')
    expect(resolveGibsDate('2026-11-25', viirsConfig)).toBe('2026-11-18')
    expect(resolveGibsDate('2010-01-01', viirsConfig)).toBe('2015-11-24')
  })
})
