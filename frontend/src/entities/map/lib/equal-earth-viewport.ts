import { geoEqualEarth } from 'd3-geo'
import { clampLatitude, normalizeLongitude } from '../../../shared/lib/geojson-utils'
import { EQUAL_EARTH_SPHERE } from './equal-earth-draw'

export interface EqualEarthCamera {
  width: number
  height: number
  baseScale: number
  scaleFactor: number
  panX: number
  panY: number
}

export function mapZoomToScaleFactor(zoom: number): number {
  return Math.max(1, Math.min(12, Math.pow(2, Math.max(0, zoom - 0.6))))
}

export function scaleFactorToMapZoom(scaleFactor: number): number {
  return Number((0.6 + Math.log2(Math.max(1, scaleFactor))).toFixed(2))
}

export function computeBaseScale(width: number, height: number): number {
  return geoEqualEarth()
    .fitExtent([[18, 18], [width - 18, height - 18]], EQUAL_EARTH_SPHERE)
    .scale()
}

export function buildEqualEarthProjection(camera: EqualEarthCamera, useBase = false) {
  const scale = useBase ? camera.baseScale : camera.baseScale * camera.scaleFactor
  const tx = useBase ? camera.width / 2 : camera.width / 2 + camera.panX
  const ty = useBase ? camera.height / 2 : camera.height / 2 + camera.panY
  return geoEqualEarth().scale(scale).translate([tx, ty])
}

export function clampEqualEarthCamera(camera: EqualEarthCamera): EqualEarthCamera {
  const maxPanX = camera.width * 0.48 * camera.scaleFactor
  const maxPanY = camera.height * 0.48 * camera.scaleFactor
  return {
    ...camera,
    panX: Math.max(-maxPanX, Math.min(maxPanX, camera.panX)),
    panY: Math.max(-maxPanY, Math.min(maxPanY, camera.panY)),
  }
}

export function applyEqualEarthZoom(
  camera: EqualEarthCamera,
  factor: number,
  anchorX: number,
  anchorY: number,
): EqualEarthCamera | null {
  const nextScale = Math.max(1, Math.min(12, camera.scaleFactor * factor))
  if (nextScale === camera.scaleFactor) return null

  const ratio = nextScale / camera.scaleFactor
  const cx = camera.width / 2
  const cy = camera.height / 2
  const panX = anchorX - cx - (anchorX - (cx + camera.panX)) * ratio
  const panY = anchorY - cy - (anchorY - (cy + camera.panY)) * ratio

  if (nextScale === 1) {
    return { ...camera, scaleFactor: 1, panX: 0, panY: 0 }
  }
  return clampEqualEarthCamera({ ...camera, scaleFactor: nextScale, panX, panY })
}

export function invertEqualEarthPoint(
  camera: EqualEarthCamera,
  x: number,
  y: number,
): [number, number] | null {
  const proj = buildEqualEarthProjection(camera)
  const coords = proj.invert?.([x, y])
  if (!coords || Number.isNaN(coords[0]) || Number.isNaN(coords[1])) return null
  const [lon, lat] = coords
  if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return null
  const reprojected = proj([lon, lat])
  if (!reprojected) return null
  const dx = reprojected[0] - x
  const dy = reprojected[1] - y
  return dx * dx + dy * dy <= 16 ? [normalizeLongitude(lon), clampLatitude(lat)] : null
}
