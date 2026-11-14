import {
  BASEMAP_PROVIDER_REGISTRY,
  buildGibsEpsg4326StaticTileUrl,
} from '../../../shared/config/geospatial'
import type { BasemapId } from '../../../shared/types/geospatial'

export interface CachedGibsRaster {
  basemapId: BasemapId
  width: number
  height: number
  data: Uint8ClampedArray
}

const gibsRasterCache = new Map<BasemapId, Promise<CachedGibsRaster | null>>()

export function loadGibs500mOverview(basemapId: BasemapId): Promise<CachedGibsRaster | null> {
  const existing = gibsRasterCache.get(basemapId)
  if (existing) {
    return existing
  }

  const promise = (async (): Promise<CachedGibsRaster | null> => {
    const config = BASEMAP_PROVIDER_REGISTRY[basemapId]
    if (!config.gibsLayerId || config.supportsTemporalTime) {
      return null
    }

    const cols = 3
    const rows = 2
    const tileSize = 512
    const canvas = document.createElement('canvas')
    canvas.width = cols * tileSize
    canvas.height = rows * tileSize
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      return null
    }

    const jobs: Promise<void>[] = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const url = buildGibsEpsg4326StaticTileUrl(basemapId, 1, row, col)
        if (!url) continue
        jobs.push(
          new Promise<void>((resolve, reject) => {
            const img = new Image()
            img.crossOrigin = 'anonymous'
            img.onload = () => {
              ctx.drawImage(img, col * tileSize, row * tileSize)
              resolve()
            }
            img.onerror = () => reject(new Error(`Tile load failed: ${url}`))
            img.src = url
          }),
        )
      }
    }

    try {
      await Promise.all(jobs)
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
      return {
        basemapId,
        width: canvas.width,
        height: canvas.height,
        data: imageData.data,
      }
    } catch {
      return null
    }
  })()

  gibsRasterCache.set(basemapId, promise)
  return promise
}
