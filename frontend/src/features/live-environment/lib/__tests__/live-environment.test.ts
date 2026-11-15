import { describe, expect, it } from 'vitest'
import {
  LIVE_GIBS_LAYERS,
  buildGibsLiveTileUrl,
  buildGibsMapLayer,
  findLiveLayer,
} from '../../../../shared/config/live-environment'
import { lonLatToModis, modisToLonLat, pointInAoi } from '../cog'
import { parsePowerMonthly } from '../power'
import {
  computeMonthlyAnomalies,
  describeValues,
  mannKendall,
  senSlope,
} from '../stats'

describe('client-side descriptive statistics', () => {
  it('preserves missing values instead of treating them as zero', () => {
    const stats = describeValues([1, null, 3, Number.NaN, 5])
    expect(stats.observationCount).toBe(5)
    expect(stats.validCount).toBe(3)
    expect(stats.missingCount).toBe(2)
    expect(stats.mean).toBe(3)
    expect(stats.median).toBe(3)
    expect(stats.min).toBe(1)
    expect(stats.max).toBe(5)
  })

  it('returns null statistics when no valid observations exist', () => {
    const stats = describeValues([null, null])
    expect(stats.validCount).toBe(0)
    expect(stats.mean).toBeNull()
    expect(stats.min).toBeNull()
  })
})

describe('Mann–Kendall and Theil–Sen', () => {
  it('detects a strong increasing monthly trend', () => {
    const values = Array.from({ length: 36 }, (_, index) => 10 + index * 0.5)
    const result = mannKendall(values)
    expect(result.direction).toBe('increasing')
    expect(result.pValue).not.toBeNull()
    expect(result.pValue!).toBeLessThan(0.05)
  })

  it('requires enough samples for a trend', () => {
    const result = mannKendall([1, 2, 3])
    expect(result.pValue).toBeNull()
    expect(result.direction).toBe('no_trend')
  })

  it('recovers a known Sen slope per year', () => {
    const timestamps = Array.from({ length: 24 }, (_, index) => {
      const year = 2020 + Math.floor(index / 12)
      const month = (index % 12) + 1
      return `${year}-${String(month).padStart(2, '0')}-01`
    })
    const values = timestamps.map((_, index) => 5 + index * 1.5)
    const result = senSlope(timestamps, values)
    expect(result.slopePerYear).not.toBeNull()
    expect(result.slopePerYear!).toBeGreaterThan(17)
    expect(result.slopePerYear!).toBeLessThan(19)
  })
})

describe('calendar-month anomalies', () => {
  it('keeps missing values missing and produces z-scores', () => {
    const timestamps = ['2020-01-01', '2020-02-01', '2021-01-01', '2021-02-01', '2022-01-01']
    const values = [1, 2, 3, null, 5]
    const result = computeMonthlyAnomalies(timestamps, values)
    expect(result.anomalies[3]).toBeNull()
    expect(result.anomalies[0]).toBeCloseTo(-1, 5)
    expect(result.anomalies[4]).toBeCloseTo(1, 5)
  })
})

describe('NASA GIBS registry', () => {
  it('uses verified layer ids and matrix sets', () => {
    const ndvi = findLiveLayer('MODIS_Terra_L3_NDVI_16Day')
    expect(ndvi).not.toBeNull()
    expect(buildGibsLiveTileUrl(ndvi!, '2026-10-16')).toContain(
      '/MODIS_Terra_L3_NDVI_16Day/default/2026-10-16/GoogleMapsCompatible_Level9/',
    )
    const layer = buildGibsMapLayer(ndvi!, '2026-10-16')
    expect(layer.tileSource.isConnected).toBe(true)
    expect(layer.availabilityStatus).toBe('connected')
    expect(layer.legend.stops.length).toBeGreaterThan(2)
    expect(layer.qaPolicy).toContain('GIBS')
    expect(layer.limitations).toContain('Never use tile colours')
  })

  it('contains the expected environmental domains', () => {
    const domains = new Set(LIVE_GIBS_LAYERS.map((layer) => layer.domain))
    expect(domains).toEqual(
      new Set(['vegetation', 'temperature', 'water', 'soil', 'cryosphere']),
    )
  })
})

describe('MODIS sinusoidal projection and AOI masking', () => {
  it('round trips lon/lat', () => {
    const projected = lonLatToModis(24.5, 48.5)
    const restored = modisToLonLat(projected.x, projected.y)
    expect(restored.lon).toBeCloseTo(24.5, 4)
    expect(restored.lat).toBeCloseTo(48.5, 4)
  })

  it('masks points inside and outside a polygon', () => {
    const geometry = {
      type: 'Polygon' as const,
      coordinates: [
        [
          [24, 48],
          [25, 48],
          [25, 49],
          [24, 49],
          [24, 48],
        ],
      ],
    }
    expect(pointInAoi(24.5, 48.5, geometry)).toBe(true)
    expect(pointInAoi(26, 48.5, geometry)).toBe(false)
  })
})

describe('NASA POWER monthly parser', () => {
  it('parses monthly values and preserves fill values as null', () => {
    const result = parsePowerMonthly(
      {
        properties: {
          parameter: {
            T2M: { '202301': 1.5, '202302': -4.0, '202413': 99 },
            PRECTOTCORR: { '202301': 2.0, '202302': -999 },
            RH2M: { '202301': 80, '202302': 75 },
          },
        },
      },
      { latitude: 48.6, longitude: 24.0, startYear: 2023, endYear: 2023 },
    )
    expect(result.series.find((s) => s.parameter === 'T2M')?.values).toEqual([1.5, -4.0])
    expect(result.series.find((s) => s.parameter === 'PRECTOTCORR')?.values).toEqual([2.0, null])
    expect(result.series[0].timestamps).toEqual(['2023-01-01', '2023-02-01'])
    expect(result.series[0].values).toHaveLength(2)
  })
})
