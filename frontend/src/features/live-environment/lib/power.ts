import {
  POWER_MONTHLY_ENDPOINT,
  POWER_PARAMETERS,
  type PowerParameter,
} from '../../../shared/config/live-environment'

export interface PowerSeries {
  parameter: PowerParameter
  label: string
  unit: string
  timestamps: string[]
  values: (number | null)[]
}

export interface PowerMonthlyResult {
  provider: 'NASA POWER'
  product: 'power_monthly_point'
  latitude: number
  longitude: number
  community: string
  startYear: number
  endYear: number
  series: PowerSeries[]
  note: string
}

interface PowerResponse {
  properties?: {
    parameter?: Record<string, Record<string, number>>
  }
  header?: { title?: string; fill_value?: number }
  messages?: unknown
}

const FILL_VALUE = -999

export function parsePowerMonthly(
  payload: PowerResponse,
  options: { latitude: number; longitude: number; startYear: number; endYear: number },
): PowerMonthlyResult {
  const parameter = payload.properties?.parameter ?? {}
  const timestamps = Object.keys(parameter.T2M ?? {})
    .filter((key) => /^\d{6}$/.test(key))
    .filter((key) => {
      const month = Number(key.slice(4, 6))
      return month >= 1 && month <= 12
    })
    .sort()
  const series: PowerSeries[] = []
  for (const [name, meta] of Object.entries(POWER_PARAMETERS)) {
    const raw = parameter[name]
    if (!raw) continue
    const values = timestamps.map((key) => {
      const value = raw[key]
      if (typeof value !== 'number' || !Number.isFinite(value) || value <= FILL_VALUE) return null
      return value
    })
    if (values.every((value) => value === null)) continue
    series.push({
      parameter: name as PowerParameter,
      label: meta.label,
      unit: meta.unit,
      timestamps: timestamps.map((key) => `${key.slice(0, 4)}-${key.slice(4, 6)}-01`),
      values,
    })
  }
  return {
    provider: 'NASA POWER',
    product: 'power_monthly_point',
    latitude: options.latitude,
    longitude: options.longitude,
    community: 'AG',
    startYear: options.startYear,
    endYear: options.endYear,
    series,
    note:
      'NASA POWER monthly point data (MERRA-2 / CERES). This is coarse reanalysis support, not a high-resolution satellite measurement. Missing/fill values remain null.',
  }
}

export async function fetchPowerMonthly(options: {
  latitude: number
  longitude: number
  startDate: string
  endDate: string
  signal?: AbortSignal
}): Promise<PowerMonthlyResult> {
  const startYear = Number(options.startDate.slice(0, 4))
  const endYear = Number(options.endDate.slice(0, 4))
  if (!Number.isInteger(startYear) || !Number.isInteger(endYear) || endYear < startYear) {
    throw new Error('NASA POWER requires a valid start/end year range.')
  }
  const params = new URLSearchParams({
    parameters: Object.keys(POWER_PARAMETERS).join(','),
    community: 'AG',
    longitude: String(options.longitude),
    latitude: String(options.latitude),
    start: String(startYear),
    end: String(endYear),
    format: 'JSON',
  })
  const response = await fetch(`${POWER_MONTHLY_ENDPOINT}?${params.toString()}`, {
    signal: options.signal,
  })
  if (!response.ok) {
    throw new Error(`NASA POWER returned HTTP ${response.status}.`)
  }
  const payload = (await response.json()) as PowerResponse
  const result = parsePowerMonthly(payload, {
    latitude: options.latitude,
    longitude: options.longitude,
    startYear,
    endYear,
  })
  if (result.series.length === 0) {
    throw new Error('NASA POWER returned no usable monthly parameters for this point.')
  }
  return result
}
