import type { ModisReadResult, ModisSeriesPoint, LiveAoiGeometry } from '../lib/cog'
import type { PowerMonthlyResult } from '../lib/power'
import type { AnomalyResult, DescriptiveStats, MannKendallResult, SenSlopeResult } from '../lib/stats'

export interface PowerScienceResult {
  kind: 'power'
  source: 'NASA POWER'
  variable: string
  unit: string
  data: PowerMonthlyResult
  stats: DescriptiveStats
  anomalies: AnomalyResult
  trend: { mannKendall: MannKendallResult; senSlope: SenSlopeResult }
  limitations: string[]
}

export interface ModisSeriesScienceResult {
  kind: 'modis-series'
  source: 'Microsoft Planetary Computer'
  collection: string
  variable: string
  unit: string
  points: ModisSeriesPoint[]
  stats: DescriptiveStats
  anomalies: AnomalyResult
  trend: { mannKendall: MannKendallResult; senSlope: SenSlopeResult }
  limitations: string[]
}

export interface ModisSnapshotScienceResult {
  kind: 'modis-snapshot'
  source: 'Microsoft Planetary Computer'
  data: ModisReadResult
  limitations: string[]
}

export type ScienceResult = PowerScienceResult | ModisSeriesScienceResult | ModisSnapshotScienceResult

export interface PowerWorkerRequest {
  kind: 'power'
  latitude: number
  longitude: number
  startDate: string
  endDate: string
  variable: string
}

export interface ModisSeriesWorkerRequest {
  kind: 'modis-series'
  collection: string
  assetKey: string
  bbox: [number, number, number, number]
  geometry: LiveAoiGeometry
  startDate: string
  endDate: string
  variable: string
  unit: string
  fallbackScale: number
  fallbackNodata: number
  maxItems: number
}

export interface ModisSnapshotWorkerRequest {
  kind: 'modis-snapshot'
  collection: string
  assetKey: string
  bbox: [number, number, number, number]
  geometry: LiveAoiGeometry
  date: string
  variable: string
  unit: string
  fallbackScale: number
  fallbackNodata: number
}

export type ScienceWorkerRequest = PowerWorkerRequest | ModisSeriesWorkerRequest | ModisSnapshotWorkerRequest

export interface ScienceWorkerMessage {
  id: number
  type: 'progress' | 'result' | 'error'
  message?: string
  completed?: number
  total?: number
  result?: ScienceResult
  error?: string
}
