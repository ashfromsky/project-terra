import { readModisAoiSeries, readModisAoiStats } from '../lib/cog'
import { fetchPowerMonthly } from '../lib/power'
import { searchStacItems } from '../lib/stac'
import { computeMonthlyAnomalies, describeValues, mannKendall, senSlope } from '../lib/stats'
import type {
  ModisSeriesScienceResult,
  ModisSnapshotScienceResult,
  PowerScienceResult,
  ScienceWorkerMessage,
  ScienceWorkerRequest,
} from '../model/science-types'

const workerScope = self as unknown as {
  onmessage: ((event: MessageEvent<ScienceWorkerRequest>) => void) | null
  postMessage: (message: ScienceWorkerMessage) => void
}

let activeRequestId = 0

function post(message: ScienceWorkerMessage): void {
  workerScope.postMessage(message)
}

function limitationsForPower(): string[] {
  return [
    'NASA POWER is coarse reanalysis/assimilation support (MERRA-2 0.5° × 0.625°, CERES 1°), not a high-resolution satellite measurement.',
    'Monthly values are aggregated by NASA POWER; missing/fill values are preserved as null.',
    'Anomalies use an in-sample calendar-month climatology and are diagnostic, not an out-of-sample validated baseline.',
    'Standard Mann–Kendall p-values can be optimistic for serially correlated monthly series.',
  ]
}

function limitationsForModis(): string[] {
  return [
    'MODIS NDVI is a 16-day 250 m composite; it does not resolve daily or sub-250 m variability.',
    'Only the MOD13Q1 NDVI asset is read; pixel reliability/VI quality layers are not yet applied.',
    'The AOI is masked in MODIS sinusoidal coordinates using a planar point-in-polygon test.',
    'Large AOIs are spatially downsampled to keep browser range requests bounded; statistics describe the sampled window.',
    'Anomalies use an in-sample calendar-month climatology; trend p-values may be optimistic for serial correlation.',
  ]
}

async function handlePower(request: Extract<ScienceWorkerRequest, { kind: 'power' }>, id: number) {
  post({ id, type: 'progress', message: 'Requesting NASA POWER monthly point series…' })
  const data = await fetchPowerMonthly({
    latitude: request.latitude,
    longitude: request.longitude,
    startDate: request.startDate,
    endDate: request.endDate,
  })
  const series = data.series.find((item) => item.parameter === request.variable) ?? data.series[0]
  if (!series) throw new Error('NASA POWER returned no requested variable.')
  const stats = describeValues(series.values)
  const anomalies = computeMonthlyAnomalies(series.timestamps, series.values)
  const mk = mannKendall(series.values)
  const sen = senSlope(series.timestamps, series.values, `${series.unit}/year`)
  const result: PowerScienceResult = {
    kind: 'power',
    source: 'NASA POWER',
    variable: series.label,
    unit: series.unit,
    data,
    stats,
    anomalies,
    trend: { mannKendall: mk, senSlope: sen },
    limitations: limitationsForPower(),
  }
  post({ id, type: 'result', result })
}

async function handleModisSnapshot(
  request: Extract<ScienceWorkerRequest, { kind: 'modis-snapshot' }>,
  id: number,
) {
  post({ id, type: 'progress', message: 'Searching Planetary Computer STAC…' })
  const items = await searchStacItems({
    collection: request.collection,
    bbox: request.bbox,
    startDate: request.date,
    endDate: request.date,
    limit: 1,
  })
  if (items.length === 0) throw new Error('No MODIS composite matched this AOI and date.')
  post({ id, type: 'progress', message: 'Signing and reading the COG window…' })
  const data = await readModisAoiStats({
    item: items[0],
    collection: request.collection,
    assetKey: request.assetKey,
    bbox: request.bbox,
    geometry: request.geometry,
    variable: request.variable,
    unit: request.unit,
    fallbackScale: request.fallbackScale,
    fallbackNodata: request.fallbackNodata,
  })
  const result: ModisSnapshotScienceResult = {
    kind: 'modis-snapshot',
    source: 'Microsoft Planetary Computer',
    data,
    limitations: limitationsForModis(),
  }
  post({ id, type: 'result', result })
}

async function handleModisSeries(
  request: Extract<ScienceWorkerRequest, { kind: 'modis-series' }>,
  id: number,
) {
  post({ id, type: 'progress', message: 'Searching MODIS composites…' })
  const { points, note } = await readModisAoiSeries({
    collection: request.collection,
    assetKey: request.assetKey,
    bbox: request.bbox,
    geometry: request.geometry,
    startDate: request.startDate,
    endDate: request.endDate,
    variable: request.variable,
    unit: request.unit,
    fallbackScale: request.fallbackScale,
    fallbackNodata: request.fallbackNodata,
    maxItems: request.maxItems,
    onProgress: (completed, total, message) =>
      post({ id, type: 'progress', completed, total, message }),
  })
  const timestamps = points.map((point) => point.timestamp)
  const values = points.map((point) => point.mean)
  const stats = describeValues(values)
  const anomalies = computeMonthlyAnomalies(timestamps, values)
  const mk = mannKendall(values)
  const sen = senSlope(timestamps, values, `${request.unit}/year`)
  const result: ModisSeriesScienceResult = {
    kind: 'modis-series',
    source: 'Microsoft Planetary Computer',
    collection: request.collection,
    variable: request.variable,
    unit: request.unit,
    points,
    stats,
    anomalies,
    trend: { mannKendall: mk, senSlope: sen },
    limitations: [...limitationsForModis(), note],
  }
  post({ id, type: 'result', result })
}

workerScope.onmessage = (event) => {
  const request = event.data
  activeRequestId += 1
  const id = activeRequestId
  void (async () => {
    try {
      if (request.kind === 'power') await handlePower(request, id)
      else if (request.kind === 'modis-series') await handleModisSeries(request, id)
      else await handleModisSnapshot(request, id)
    } catch (error) {
      post({ id, type: 'error', error: error instanceof Error ? error.message : String(error) })
    }
  })()
}
