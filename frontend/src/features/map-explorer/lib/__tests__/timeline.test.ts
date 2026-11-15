import { describe, expect, it } from 'vitest'
import {
  computeTimelineSliderState,
  dayIndexToIsoDate,
  stepIsoDate,
  stepTimelineDate,
} from '../timeline'

describe('timeline slider helpers', () => {
  it('places the slider thumb at the right edge when displayDate equals today', () => {
    const state = computeTimelineSliderState({
      dateRangeStart: '2020-01-01',
      dateRangeEnd: '2026-11-18',
      displayDate: '2026-11-18',
      maxSelectableDate: '2026-11-18',
    })

    expect(state.min).toBe(0)
    expect(state.max).toBe(state.totalDays)
    expect(state.value).toBe(state.totalDays)
    expect(dayIndexToIsoDate(state.rangeMinMs, state.value)).toBe('2026-11-18')
  })

  it('expands the upper range bound up to maxSelectableDate when displayDate exceeds dateRangeEnd', () => {
    const state = computeTimelineSliderState({
      dateRangeStart: '2020-01-01',
      dateRangeEnd: '2025-12-01',
      displayDate: '2026-11-18',
      maxSelectableDate: '2026-11-18',
    })

    expect(state.effectiveRangeEnd).toBe('2026-11-18')
    expect(state.value).toBe(state.totalDays)
    expect(dayIndexToIsoDate(state.rangeMinMs, state.value)).toBe('2026-11-18')
  })

  it('maps any day index back to the exact UTC ISO date without drift', () => {
    const state = computeTimelineSliderState({
      dateRangeStart: '2020-01-01',
      dateRangeEnd: '2026-11-18',
      displayDate: '2024-05-24',
      maxSelectableDate: '2026-11-18',
    })

    expect(dayIndexToIsoDate(state.rangeMinMs, state.value)).toBe('2024-05-24')
    expect(dayIndexToIsoDate(state.rangeMinMs, 0)).toBe('2020-01-01')
  })

  it('steps forward and backward by cadence and clamps to bounds', () => {
    expect(
      stepTimelineDate({
        currentDate: '2026-11-18',
        cadence: '16-day',
        direction: -1,
        minDate: '2020-01-01',
        maxDate: '2026-11-18',
      }),
    ).toBe('2026-11-02')

    expect(
      stepTimelineDate({
        currentDate: '2026-11-10',
        cadence: '16-day',
        direction: 1,
        minDate: '2020-01-01',
        maxDate: '2026-11-18',
      }),
    ).toBe('2026-11-18')

    expect(
      stepTimelineDate({
        currentDate: '2020-01-03',
        cadence: '16-day',
        direction: -1,
        minDate: '2020-01-01',
        maxDate: '2026-11-18',
      }),
    ).toBe('2020-01-01')
  })

  it('steps daily, monthly, and multi-year cadences accurately', () => {
    expect(stepIsoDate('2026-11-18', 'daily', -1)).toBe('2026-11-17')
    expect(stepIsoDate('2026-11-18', 'monthly', -1)).toBe('2026-10-18')
    expect(stepIsoDate('2026-11-18', 'multi-year', -1)).toBe('2025-11-18')
  })
})
