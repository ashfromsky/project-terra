import type {
  AoiFeature,
  AoiFeatureCollection,
  AoiGeometry,
  AoiRole,
  AoiShapeType,
} from '../types/geospatial'

const EARTH_RADIUS_KM = 6371.0088

export function normalizeLongitude(lon: number): number {
  let normalized = ((lon + 180) % 360 + 360) % 360 - 180
  if (normalized === -180 && lon > 0) {
    normalized = 180
  }
  return Number(normalized.toFixed(5))
}

export function clampLatitude(lat: number): number {
  return Number(Math.max(-90, Math.min(90, lat)).toFixed(5))
}

export function formatCoordinatePair(lon: number, lat: number): string {
  const latDir = lat >= 0 ? 'N' : 'S'
  const lonDir = lon >= 0 ? 'E' : 'W'
  return `${Math.abs(lat).toFixed(3)}°${latDir}, ${Math.abs(lon).toFixed(3)}°${lonDir}`
}

function toRadians(deg: number): number {
  return (deg * Math.PI) / 180
}

export function computeRingSignedArea(ring: readonly [number, number][]): number {
  let area = 0
  for (let i = 0; i < ring.length - 1; i++) {
    const [x1, y1] = ring[i]
    const [x2, y2] = ring[i + 1]
    area += x1 * y2 - x2 * y1
  }
  return area / 2
}

export function ensureCounterClockwiseRing(
  ring: readonly [number, number][],
): [number, number][] {
  const closed = closeRing(ring)
  if (computeRingSignedArea(closed) < 0) {
    return [...closed].reverse()
  }
  return closed
}

export function closeRing(ring: readonly [number, number][]): [number, number][] {
  if (ring.length === 0) return []
  const normalized = ring.map(
    ([lon, lat]) => [normalizeLongitude(lon), clampLatitude(lat)] as [number, number],
  )
  const first = normalized[0]
  const last = normalized[normalized.length - 1]
  if (first[0] !== last[0] || first[1] !== last[1]) {
    normalized.push([first[0], first[1]])
  }
  return normalized
}

function computeSphericalRingAreaKm2(ring: readonly [number, number][]): number {
  if (ring.length < 4) return 0
  let total = 0
  for (let i = 0; i < ring.length - 1; i++) {
    const [lon1, lat1] = ring[i]
    const [lon2, lat2] = ring[i + 1]
    total +=
      toRadians(lon2 - lon1) *
      (2 + Math.sin(toRadians(lat1)) + Math.sin(toRadians(lat2)))
  }
  return Math.abs((total * EARTH_RADIUS_KM * EARTH_RADIUS_KM) / 2)
}

export function computeApproxGeometryAreaKm2(geometry: AoiGeometry): number {
  if (geometry.type === 'Polygon') {
    const outer = computeSphericalRingAreaKm2(
      geometry.coordinates[0] as [number, number][],
    )
    let holes = 0
    for (let i = 1; i < geometry.coordinates.length; i++) {
      holes += computeSphericalRingAreaKm2(
        geometry.coordinates[i] as [number, number][],
      )
    }
    return Math.max(0, Math.round(outer - holes))
  }

  let sum = 0
  for (const poly of geometry.coordinates) {
    const outer = computeSphericalRingAreaKm2(poly[0] as [number, number][])
    let holes = 0
    for (let i = 1; i < poly.length; i++) {
      holes += computeSphericalRingAreaKm2(poly[i] as [number, number][])
    }
    sum += Math.max(0, outer - holes)
  }
  return Math.round(sum)
}

export function computeGeometryBboxAndCentroid(geometry: AoiGeometry): {
  bbox: [number, number, number, number]
  centroid: [number, number]
} {
  let minLon = 180
  let minLat = 90
  let maxLon = -180
  let maxLat = -90
  let lonSum = 0
  let latSum = 0
  let count = 0

  const visitRing = (ring: readonly number[][]) => {
    const limit = ring.length > 1 ? ring.length - 1 : ring.length
    for (let i = 0; i < limit; i++) {
      const [lon, lat] = ring[i]
      if (lon < minLon) minLon = lon
      if (lon > maxLon) maxLon = lon
      if (lat < minLat) minLat = lat
      if (lat > maxLat) maxLat = lat
      lonSum += lon
      latSum += lat
      count += 1
    }
  }

  if (geometry.type === 'Polygon') {
    if (geometry.coordinates[0]) visitRing(geometry.coordinates[0])
  } else {
    for (const poly of geometry.coordinates) {
      if (poly[0]) visitRing(poly[0])
    }
  }

  if (count === 0) {
    return { bbox: [0, 0, 0, 0], centroid: [0, 0] }
  }

  return {
    bbox: [
      Number(minLon.toFixed(4)),
      Number(minLat.toFixed(4)),
      Number(maxLon.toFixed(4)),
      Number(maxLat.toFixed(4)),
    ],
    centroid: [
      Number((lonSum / count).toFixed(4)),
      Number((latSum / count).toFixed(4)),
    ],
  }
}

export function createRectangleGeometry(
  cornerA: [number, number],
  cornerB: [number, number],
): AoiGeometry {
  const minLon = normalizeLongitude(Math.min(cornerA[0], cornerB[0]))
  const maxLon = normalizeLongitude(Math.max(cornerA[0], cornerB[0]))
  const minLat = clampLatitude(Math.min(cornerA[1], cornerB[1]))
  const maxLat = clampLatitude(Math.max(cornerA[1], cornerB[1]))

  return {
    type: 'Polygon',
    coordinates: [
      ensureCounterClockwiseRing([
        [minLon, minLat],
        [maxLon, minLat],
        [maxLon, maxLat],
        [minLon, maxLat],
        [minLon, minLat],
      ]),
    ],
  }
}

export function createPolygonGeometry(
  vertices: readonly [number, number][],
): AoiGeometry {
  return {
    type: 'Polygon',
    coordinates: [ensureCounterClockwiseRing(vertices)],
  }
}

export function buildAoiFeature(params: {
  id: string
  name: string
  role: AoiRole
  shapeType: AoiShapeType
  geometry: AoiGeometry
  isoA3?: string
}): AoiFeature {
  const { bbox, centroid } = computeGeometryBboxAndCentroid(params.geometry)
  const approxAreaKm2 = computeApproxGeometryAreaKm2(params.geometry)

  return {
    type: 'Feature',
    id: params.id,
    properties: {
      id: params.id,
      name: params.name,
      role: params.role,
      shapeType: params.shapeType,
      sourceCrs: 'EPSG:4326',
      approxAreaKm2,
      bbox,
      centroid,
      createdAt: new Date().toISOString(),
      isoA3: params.isoA3,
    },
    geometry: params.geometry,
  }
}

export function buildAoiFeatureCollection(
  aois: readonly AoiFeature[],
): AoiFeatureCollection {
  return {
    type: 'FeatureCollection',
    features: [...aois],
  }
}

export function exportAoiGeoJsonFile(
  aois: readonly AoiFeature[],
  filename = 'terra-aoi-wgs84.geojson',
): void {
  const collection = buildAoiFeatureCollection(aois)
  const payload = JSON.stringify(collection, null, 2)
  const blob = new Blob([payload], { type: 'application/geo+json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
