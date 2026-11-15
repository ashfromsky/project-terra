import type { DescriptiveStats } from './stats'
import { describeValues } from './stats'
import { searchStacItems, signPlanetaryComputerAsset, type StacItem } from './stac'

const MODIS_SINUSOIDAL_RADIUS_M = 6_371_007.181
const GEOTIFF_ESM_URL = 'https://esm.sh/geotiff@2.1.3'
const DEFAULT_MAX_SAMPLE_DIMENSION = 512

export type LiveAoiGeometry =
  | { type: 'Polygon'; coordinates: number[][][] }
  | { type: 'MultiPolygon'; coordinates: number[][][][] }

export interface ModisReadResult {
  provider: 'Microsoft Planetary Computer'
  collection: string
  itemId: string
  assetKey: string
  variable: string
  unit: string
  timestamp: string
  scale: number
  nodata: number
  window: [number, number, number, number]
  sampleWidth: number
  sampleHeight: number
  maskedPixelCount: number
  validPixelCount: number
  validFraction: number
  stats: DescriptiveStats
  note: string
}

export interface ModisSeriesPoint {
  timestamp: string
  itemId: string
  mean: number | null
  validPixelCount: number
  maskedPixelCount: number
  validFraction: number
}

interface GeoTiffImage {
  getWidth(): number
  getHeight(): number
  getBoundingBox(): [number, number, number, number]
  getFileDirectory(): Record<string, unknown>
  readRasters(options: Record<string, unknown>): Promise<ArrayLike<number>[]>
}

interface GeoTiffReader {
  getImage(): Promise<GeoTiffImage>
}

interface GeoTiffModule {
  fromUrl(url: string, options?: Record<string, unknown>): Promise<GeoTiffReader>
}

async function loadGeoTiff(): Promise<GeoTiffModule> {
  return (await import(/* @vite-ignore */ GEOTIFF_ESM_URL)) as GeoTiffModule
}

export function lonLatToModis(lon: number, lat: number): { x: number; y: number } {
  const phi = (lat * Math.PI) / 180
  const lambda = (lon * Math.PI) / 180
  return {
    x: MODIS_SINUSOIDAL_RADIUS_M * lambda * Math.cos(phi),
    y: MODIS_SINUSOIDAL_RADIUS_M * phi,
  }
}

export function modisToLonLat(x: number, y: number): { lon: number; lat: number } {
  const phi = y / MODIS_SINUSOIDAL_RADIUS_M
  const cosPhi = Math.cos(phi)
  const lambda = cosPhi === 0 ? 0 : x / (MODIS_SINUSOIDAL_RADIUS_M * cosPhi)
  return { lon: (lambda * 180) / Math.PI, lat: (phi * 180) / Math.PI }
}

function eachCoordinate(
  geometry: LiveAoiGeometry,
  visit: (lon: number, lat: number) => void,
): void {
  if (geometry.type === 'Polygon') {
    for (const ring of geometry.coordinates) {
      for (const position of ring) visit(position[0], position[1])
    }
    return
  }
  for (const polygon of geometry.coordinates) {
    for (const ring of polygon) {
      for (const position of ring) visit(position[0], position[1])
    }
  }
}

export function projectedAoiBounds(
  geometry: LiveAoiGeometry,
  bbox: [number, number, number, number],
): { minX: number; minY: number; maxX: number; maxY: number } {
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  eachCoordinate(geometry, (lon, lat) => {
    const point = lonLatToModis(lon, lat)
    minX = Math.min(minX, point.x)
    minY = Math.min(minY, point.y)
    maxX = Math.max(maxX, point.x)
    maxY = Math.max(maxY, point.y)
  })
  for (const [lon, lat] of [
    [bbox[0], bbox[1]],
    [bbox[0], bbox[3]],
    [bbox[2], bbox[1]],
    [bbox[2], bbox[3]],
  ]) {
    const point = lonLatToModis(lon, lat)
    minX = Math.min(minX, point.x)
    minY = Math.min(minY, point.y)
    maxX = Math.max(maxX, point.x)
    maxY = Math.max(maxY, point.y)
  }
  return { minX, minY, maxX, maxY }
}

function pointInRing(lon: number, lat: number, ring: number[][]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const xi = ring[i][0]
    const yi = ring[i][1]
    const xj = ring[j][0]
    const yj = ring[j][1]
    const intersects =
      yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi || Number.EPSILON) + xi
    if (intersects) inside = !inside
  }
  return inside
}

function pointInPolygon(lon: number, lat: number, polygon: number[][][]): boolean {
  if (!pointInRing(lon, lat, polygon[0] ?? [])) return false
  for (let i = 1; i < polygon.length; i += 1) {
    if (pointInRing(lon, lat, polygon[i])) return false
  }
  return true
}

export function pointInAoi(lon: number, lat: number, geometry: LiveAoiGeometry): boolean {
  if (geometry.type === 'Polygon') return pointInPolygon(lon, lat, geometry.coordinates)
  return geometry.coordinates.some((polygon) => pointInPolygon(lon, lat, polygon))
}

function parseNodata(raw: unknown, fallback: number): number {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw !== 'string') return fallback
  const cleaned = raw.replaceAll(String.fromCharCode(0), '').trim()
  const parsed = Number(cleaned)
  return Number.isFinite(parsed) ? parsed : fallback
}

function readScale(item: StacItem, assetKey: string, fallback: number): number {
  const band = item.assets[assetKey]?.['raster:bands']?.[0]
  return typeof band?.scale === 'number' && Number.isFinite(band.scale) ? band.scale : fallback
}

export async function readModisAoiStats(options: {
  item: StacItem
  collection: string
  assetKey: string
  bbox: [number, number, number, number]
  geometry: LiveAoiGeometry
  variable: string
  unit: string
  fallbackScale: number
  fallbackNodata: number
  maxSampleDimension?: number
  signal?: AbortSignal
}): Promise<ModisReadResult> {
  const { item } = options
  const asset = item.assets[options.assetKey]
  if (!asset?.href) {
    throw new Error(`STAC item ${item.id} has no ${options.assetKey} asset.`)
  }
  if (options.signal?.aborted) throw new Error('Calculation cancelled.')
  const signedUrl = await signPlanetaryComputerAsset(asset.href, options.signal)
  if (options.signal?.aborted) throw new Error('Calculation cancelled.')
  const geoTiff = await loadGeoTiff()
  const tiff = await geoTiff.fromUrl(signedUrl, { cache: true, blockSize: 65_536 })
  const image = await tiff.getImage()
  const [imgMinX, imgMinY, imgMaxX, imgMaxY] = image.getBoundingBox()
  const imageWidth = image.getWidth()
  const imageHeight = image.getHeight()
  const pixelWidth = (imgMaxX - imgMinX) / imageWidth
  const pixelHeight = (imgMaxY - imgMinY) / imageHeight
  const aoi = projectedAoiBounds(options.geometry, options.bbox)
  const minX = Math.max(imgMinX, aoi.minX)
  const maxX = Math.min(imgMaxX, aoi.maxX)
  const minY = Math.max(imgMinY, aoi.minY)
  const maxY = Math.min(imgMaxY, aoi.maxY)
  if (minX >= maxX || minY >= maxY) {
    throw new Error('The selected AOI does not intersect this MODIS granule.')
  }
  const col0 = Math.max(0, Math.floor((minX - imgMinX) / pixelWidth) - 1)
  const col1 = Math.min(imageWidth, Math.ceil((maxX - imgMinX) / pixelWidth) + 1)
  const row0 = Math.max(0, Math.floor((imgMaxY - maxY) / pixelHeight) - 1)
  const row1 = Math.min(imageHeight, Math.ceil((imgMaxY - minY) / pixelHeight) + 1)
  const window: [number, number, number, number] = [col0, row0, col1, row1]
  const windowWidth = Math.max(1, col1 - col0)
  const windowHeight = Math.max(1, row1 - row0)
  const maxDimension = options.maxSampleDimension ?? DEFAULT_MAX_SAMPLE_DIMENSION
  const scaleDown = Math.max(1, Math.ceil(Math.max(windowWidth, windowHeight) / maxDimension))
  const sampleWidth = Math.max(1, Math.floor(windowWidth / scaleDown))
  const sampleHeight = Math.max(1, Math.floor(windowHeight / scaleDown))
  const rasters = await image.readRasters({
    window,
    samples: [0],
    interleave: false,
    width: sampleWidth,
    height: sampleHeight,
    resampleMethod: 'nearest',
  })
  if (options.signal?.aborted) throw new Error('Calculation cancelled.')
  const array = rasters[0]
  const fileDirectory = image.getFileDirectory()
  const nodata = parseNodata(fileDirectory.GDAL_NODATA, options.fallbackNodata)
  const scale = readScale(item, options.assetKey, options.fallbackScale)
  const values: (number | null)[] = []
  let maskedPixelCount = 0
  const stepX = (maxX - minX) / sampleWidth
  const stepY = (maxY - minY) / sampleHeight
  for (let row = 0; row < sampleHeight; row += 1) {
    for (let col = 0; col < sampleWidth; col += 1) {
      const x = minX + (col + 0.5) * stepX
      const y = maxY - (row + 0.5) * stepY
      const { lon, lat } = modisToLonLat(x, y)
      if (!pointInAoi(lon, lat, options.geometry)) continue
      maskedPixelCount += 1
      const index = row * sampleWidth + col
      const raw = array[index]
      if (!Number.isFinite(raw) || raw === nodata || raw <= -2999) {
        values.push(null)
        continue
      }
      values.push(raw * scale)
    }
  }
  const stats = describeValues(values)
  const validPixelCount = stats.validCount
  const validFraction = maskedPixelCount > 0 ? validPixelCount / maskedPixelCount : 0
  const timestamp = item.properties.start_datetime ?? item.properties.datetime ?? 'unknown'
  return {
    provider: 'Microsoft Planetary Computer',
    collection: options.collection,
    itemId: item.id,
    assetKey: options.assetKey,
    variable: options.variable,
    unit: options.unit,
    timestamp,
    scale,
    nodata,
    window,
    sampleWidth,
    sampleHeight,
    maskedPixelCount,
    validPixelCount,
    validFraction,
    stats,
    note:
      'MODIS sinusoidal COG window read in the browser. Values are scaled by the product scale factor; fill/NoData pixels remain missing. QA layers are not yet applied.',
  }
}

export async function readModisAoiSeries(options: {
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
  signal?: AbortSignal
  onProgress?: (completed: number, total: number, message: string) => void
}): Promise<{ points: ModisSeriesPoint[]; items: StacItem[]; note: string }> {
  const candidateItems = await searchStacItems({
    collection: options.collection,
    bbox: options.bbox,
    startDate: options.startDate,
    endDate: options.endDate,
    limit: Math.min(100, options.maxItems * 3),
    signal: options.signal,
  })
  if (candidateItems.length === 0) {
    throw new Error('No MODIS composites matched this AOI and date range.')
  }
  // Adjacent MODIS tiles can overlap the same AOI on the same composite date.
  // Keep the tile with the largest bbox overlap and read each observation date once.
  const byDate = new Map<string, { item: StacItem; overlap: number }>()
  for (const item of candidateItems) {
    // The Planetary Computer collection contains both Terra (MOD13Q1) and
    // Aqua (MYD13Q1) products; keep the requested Terra product only.
    if (!item.id.startsWith('MOD13Q1')) continue
    const key = (item.properties.start_datetime ?? item.properties.datetime ?? item.id).slice(0, 10)
    const overlap =
      Math.max(0, Math.min(item.bbox[2], options.bbox[2]) - Math.max(item.bbox[0], options.bbox[0])) *
      Math.max(0, Math.min(item.bbox[3], options.bbox[3]) - Math.max(item.bbox[1], options.bbox[1]))
    const existing = byDate.get(key)
    if (!existing || overlap > existing.overlap) {
      byDate.set(key, { item, overlap })
    }
  }
  const items = [...byDate.values()]
    .map((entry) => entry.item)
    .sort((a, b) =>
      (a.properties.start_datetime ?? a.properties.datetime ?? a.id).localeCompare(
        b.properties.start_datetime ?? b.properties.datetime ?? b.id,
      ),
    )
    .slice(0, options.maxItems)
  const points: ModisSeriesPoint[] = []
  const failures: string[] = []
  let nextIndex = 0
  let completed = 0
  const worker = async () => {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      const item = items[index]
      try {
        const result = await readModisAoiStats({
          item,
          collection: options.collection,
          assetKey: options.assetKey,
          bbox: options.bbox,
          geometry: options.geometry,
          variable: options.variable,
          unit: options.unit,
          fallbackScale: options.fallbackScale,
          fallbackNodata: options.fallbackNodata,
          maxSampleDimension: 256,
          signal: options.signal,
        })
        points.push({
          timestamp: result.timestamp,
          itemId: result.itemId,
          mean: result.stats.mean,
          validPixelCount: result.validPixelCount,
          maskedPixelCount: result.maskedPixelCount,
          validFraction: result.validFraction,
        })
      } catch (error) {
        failures.push(`${item.id}: ${error instanceof Error ? error.message : String(error)}`)
      }
      completed += 1
      options.onProgress?.(completed, items.length, `Processed ${completed}/${items.length} composites`)
    }
  }
  const concurrency = 1
  await Promise.all(Array.from({ length: concurrency }, () => worker()))
  if (options.signal?.aborted) throw new Error('Calculation cancelled.')
  points.sort((a, b) => a.timestamp.localeCompare(b.timestamp))
  if (points.length === 0) {
    throw new Error(`Could not read any MODIS composites. ${failures.slice(0, 2).join(' ')}`)
  }
  return {
    points,
    items,
    note:
      failures.length > 0
        ? `${failures.length} composite(s) could not be read and were left missing. ${failures[0]}`
        : 'All requested MODIS composites were read directly from Planetary Computer COGs in the browser.',
  }
}
