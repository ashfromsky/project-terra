import {
  buildAoiFeature,
  createPolygonGeometry,
  createRectangleGeometry,
} from '../../../shared/lib/geojson-utils'
import type { CountrySelectionSummary } from '../../../shared/store/ui-store'
import type { AoiFeature, AoiGeometry, AoiRole } from '../../../shared/types/geospatial'

let aoiSequence = 1

export function nextAoiSequence(): number {
  return aoiSequence++
}

export function mergeRoleExclusiveAoi(aois: AoiFeature[], nextFeature: AoiFeature): AoiFeature[] {
  const role = nextFeature.properties.role
  return [
    ...aois.filter((a) => role === 'primary' || a.properties.role !== role),
    nextFeature,
  ]
}

export function buildDraftCompletionAoi(params: {
  interactionMode: string
  draftVertices: [number, number][]
  activeAoiRole: AoiRole
  lon?: number
  lat?: number
}): AoiFeature | null {
  const { interactionMode, draftVertices, activeAoiRole, lon, lat } = params
  const vertices = [...draftVertices]
  const roleLabel =
    activeAoiRole === 'regionA' ? 'Region A' : activeAoiRole === 'regionB' ? 'Region B' : 'AOI'

  if (typeof lon === 'number' && typeof lat === 'number') {
    if (interactionMode === 'draw-rectangle' && vertices.length >= 1) {
      const seq = nextAoiSequence()
      return buildAoiFeature({
        id: `aoi-${seq}`,
        name: `${roleLabel} Rectangle ${seq}`,
        role: activeAoiRole,
        shapeType: 'rectangle',
        geometry: createRectangleGeometry(vertices[0], [lon, lat]),
      })
    }
    const last = vertices[vertices.length - 1]
    if (!last || last[0] !== lon || last[1] !== lat) {
      vertices.push([lon, lat])
    }
  }

  if (vertices.length < 3) return null

  const seq = nextAoiSequence()
  return buildAoiFeature({
    id: `aoi-${seq}`,
    name: `${roleLabel} Polygon ${seq}`,
    role: activeAoiRole,
    shapeType: 'polygon',
    geometry: createPolygonGeometry(vertices),
  })
}

export function buildCountryAoi(
  country: CountrySelectionSummary,
  geometry: AoiGeometry,
  role: AoiRole,
): AoiFeature {
  const seq = nextAoiSequence()
  return buildAoiFeature({
    id: `aoi-${country.isoA3.toLowerCase()}-${seq}`,
    name: `${country.name} (${country.isoA3})`,
    role,
    shapeType: 'feature',
    geometry,
    isoA3: country.isoA3,
  })
}

export function assignAoiRoleInList(
  aois: AoiFeature[],
  aoiId: string,
  role: AoiRole,
): AoiFeature[] {
  return aois.map((aoi) => {
    if (aoi.properties.id === aoiId) {
      return { ...aoi, properties: { ...aoi.properties, role } }
    }
    if (role !== 'primary' && aoi.properties.role === role) {
      return { ...aoi, properties: { ...aoi.properties, role: 'primary' } }
    }
    return aoi
  })
}
