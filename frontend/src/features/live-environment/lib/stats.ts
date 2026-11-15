/** Pure client-side statistical helpers. No React, DOM, or network dependencies. */

export interface DescriptiveStats {
  observationCount: number
  validCount: number
  missingCount: number
  mean: number | null
  median: number | null
  min: number | null
  max: number | null
  standardDeviation: number | null
  p10: number | null
  p90: number | null
}

export type TrendDirection = 'increasing' | 'decreasing' | 'no_trend'

export interface MannKendallResult {
  sampleCount: number
  sStatistic: number
  variance: number
  zStatistic: number | null
  pValue: number | null
  kendallTau: number | null
  direction: TrendDirection
  alpha: number
  significant: boolean
  note: string
}

export interface SenSlopeResult {
  slopePerYear: number | null
  intercept: number | null
  ciLow: number | null
  ciHigh: number | null
  pairwiseSlopeCount: number
  unit: string
  note: string
}

export interface AnomalyPoint {
  timestamp: string
  value: number | null
  anomaly: number | null
  baselineMean: number | null
  baselineStandardDeviation: number | null
}

export interface AnomalyResult {
  baseline: 'calendar_month_in_sample'
  timestamps: string[]
  values: (number | null)[]
  anomalies: (number | null)[]
  baselineMean: (number | null)[]
  baselineStandardDeviation: (number | null)[]
  note: string
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function quantile(sorted: readonly number[], fraction: number): number | null {
  if (sorted.length === 0) return null
  if (sorted.length === 1) return sorted[0]
  const position = (sorted.length - 1) * fraction
  const lower = Math.floor(position)
  const upper = Math.ceil(position)
  if (lower === upper) return sorted[lower]
  const weight = position - lower
  return sorted[lower] * (1 - weight) + sorted[upper] * weight
}

export function describeValues(values: readonly (number | null | undefined)[]): DescriptiveStats {
  const valid = values.filter(isFiniteNumber).sort((a, b) => a - b)
  const validCount = valid.length
  const observationCount = values.length
  if (validCount === 0) {
    return {
      observationCount,
      validCount: 0,
      missingCount: observationCount,
      mean: null,
      median: null,
      min: null,
      max: null,
      standardDeviation: null,
      p10: null,
      p90: null,
    }
  }
  const mean = valid.reduce((sum, value) => sum + value, 0) / validCount
  const variance =
    validCount > 1
      ? valid.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (validCount - 1)
      : 0
  return {
    observationCount,
    validCount,
    missingCount: observationCount - validCount,
    mean,
    median: quantile(valid, 0.5),
    min: valid[0],
    max: valid[validCount - 1],
    standardDeviation: Math.sqrt(variance),
    p10: quantile(valid, 0.1),
    p90: quantile(valid, 0.9),
  }
}

function erfApproximation(x: number): number {
  // Abramowitz & Stegun 7.1.26, sufficient for two-sided p-values.
  const sign = x < 0 ? -1 : 1
  const ax = Math.abs(x)
  const t = 1 / (1 + 0.3275911 * ax)
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t *
      Math.exp(-ax * ax)
  return sign * y
}

function normalCdf(z: number): number {
  return 0.5 * (1 + erfApproximation(z / Math.SQRT2))
}

export function mannKendall(
  values: readonly (number | null | undefined)[],
  alpha = 0.05,
): MannKendallResult {
  const valid = values.filter(isFiniteNumber)
  const n = valid.length
  if (n < 6) {
    return {
      sampleCount: n,
      sStatistic: 0,
      variance: 0,
      zStatistic: null,
      pValue: null,
      kendallTau: null,
      direction: 'no_trend',
      alpha,
      significant: false,
      note: 'Mann–Kendall requires at least 6 valid observations.',
    }
  }
  let s = 0
  for (let i = 0; i < n - 1; i += 1) {
    for (let j = i + 1; j < n; j += 1) {
      s += Math.sign(valid[j] - valid[i])
    }
  }
  const groups = new Map<number, number>()
  for (const value of valid) groups.set(value, (groups.get(value) ?? 0) + 1)
  const tieCorrection = [...groups.values()].reduce(
    (sum, count) => sum + count * (count - 1) * (2 * count + 5),
    0,
  )
  const variance = (n * (n - 1) * (2 * n + 5) - tieCorrection) / 18
  const z =
    variance > 0
      ? s > 0
        ? (s - 1) / Math.sqrt(variance)
        : s < 0
          ? (s + 1) / Math.sqrt(variance)
          : 0
      : null
  const pValue = z === null ? null : Math.min(1, 2 * (1 - normalCdf(Math.abs(z))))
  const directions = valid.reduce((sum, value, index) => {
    if (index === 0) return sum
    return sum + Math.sign(value - valid[index - 1])
  }, 0)
  const direction: TrendDirection =
    pValue !== null && pValue < alpha
      ? directions > 0
        ? 'increasing'
        : 'decreasing'
      : 'no_trend'
  return {
    sampleCount: n,
    sStatistic: s,
    variance,
    zStatistic: z,
    pValue,
    kendallTau: (2 * s) / (n * (n - 1)),
    direction,
    alpha,
    significant: pValue !== null && pValue < alpha,
    note:
      'Standard Mann–Kendall test; monthly series may exhibit serial autocorrelation, so p-values can be optimistic. Seasonal Mann–Kendall is not applied here.',
  }
}

function timeInYears(timestamp: string): number | null {
  const parsed = Date.parse(timestamp)
  return Number.isNaN(parsed) ? null : parsed / (365.2425 * 86_400_000)
}

export function senSlope(
  timestamps: readonly string[],
  values: readonly (number | null | undefined)[],
  unit = 'unit/year',
): SenSlopeResult {
  const points: { t: number; y: number }[] = []
  for (let i = 0; i < Math.min(timestamps.length, values.length); i += 1) {
    const value = values[i]
    const t = timeInYears(timestamps[i])
    if (isFiniteNumber(value) && t !== null) points.push({ t, y: value })
  }
  if (points.length < 4) {
    return {
      slopePerYear: null,
      intercept: null,
      ciLow: null,
      ciHigh: null,
      pairwiseSlopeCount: 0,
      unit,
      note: 'Theil–Sen slope requires at least 4 paired observations.',
    }
  }
  const slopes: number[] = []
  for (let i = 0; i < points.length - 1; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      const dt = points[j].t - points[i].t
      if (dt !== 0) slopes.push((points[j].y - points[i].y) / dt)
    }
  }
  slopes.sort((a, b) => a - b)
  const slope = quantile(slopes, 0.5)
  const intercepts = points.map((point) =>
    slope === null ? Number.NaN : point.y - slope * point.t,
  )
  const intercept = quantile(intercepts.filter(isFiniteNumber).sort((a, b) => a - b), 0.5)
  return {
    slopePerYear: slope,
    intercept,
    ciLow: quantile(slopes, 0.025),
    ciHigh: quantile(slopes, 0.975),
    pairwiseSlopeCount: slopes.length,
    unit,
    note: 'Theil–Sen median pairwise slope; confidence bounds are pairwise-slope quantiles (approx. 95%).',
  }
}

export function calendarMonth(timestamp: string): number | null {
  const iso = timestamp.slice(0, 10)
  const match = /^\d{4}-(\d{2})-\d{2}$/.exec(iso)
  if (!match) return null
  const month = Number(match[1])
  return month >= 1 && month <= 12 ? month : null
}

export function computeMonthlyAnomalies(
  timestamps: readonly string[],
  values: readonly (number | null | undefined)[],
): AnomalyResult {
  const byMonth = new Map<number, number[]>()
  for (let i = 0; i < timestamps.length; i += 1) {
    const month = calendarMonth(timestamps[i])
    const value = values[i]
    if (month === null || !isFiniteNumber(value)) continue
    const bucket = byMonth.get(month) ?? []
    bucket.push(value)
    byMonth.set(month, bucket)
  }
  const statsByMonth = new Map<number, { mean: number; sd: number | null }>()
  for (const [month, bucket] of byMonth) {
    const mean = bucket.reduce((sum, value) => sum + value, 0) / bucket.length
    const sd =
      bucket.length > 1
        ? Math.sqrt(
            bucket.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (bucket.length - 1),
          )
        : null
    statsByMonth.set(month, { mean, sd })
  }
  const anomalies = values.map((value, index) => {
    const month = calendarMonth(timestamps[index])
    if (month === null || !isFiniteNumber(value)) return null
    const stats = statsByMonth.get(month)
    if (!stats || stats.sd === null || stats.sd === 0) return null
    return (value - stats.mean) / stats.sd
  })
  return {
    baseline: 'calendar_month_in_sample',
    timestamps: [...timestamps],
    values: values.map((value) => (isFiniteNumber(value) ? value : null)),
    anomalies,
    baselineMean: values.map((_, index) => {
      const month = calendarMonth(timestamps[index])
      return month === null ? null : (statsByMonth.get(month)?.mean ?? null)
    }),
    baselineStandardDeviation: values.map((_, index) => {
      const month = calendarMonth(timestamps[index])
      return month === null ? null : (statsByMonth.get(month)?.sd ?? null)
    }),
    note: 'Standardized anomalies use an in-sample calendar-month climatology. This is a diagnostic, not an out-of-sample validated baseline.',
  }
}

export function formatNumber(value: number | null, digits = 3): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return value.toFixed(digits)
}
