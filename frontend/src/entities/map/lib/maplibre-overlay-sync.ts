import type { Feature, Geometry } from 'geojson'
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl'
import { BASEMAP_PROVIDER_REGISTRY } from '../../../shared/config/geospatial'
import { createPolygonGeometry, createRectangleGeometry } from '../../../shared/lib/geojson-utils'
import {
  CONTINENT_AND_OCEAN_LABELS,
  MAJOR_COUNTRY_LABELS,
} from '../../../widgets/world-map/config/cartographic-data'
import type { MapRenderState } from '../model/map-renderer'
import { buildCountryColorExpression } from './maplibre-style-builder'

export function syncMapLibreLayersAndSources(map: MapLibreMap, state: MapRenderState): void {
  if (state.interactionMode === 'draw-polygon') {
    map.doubleClickZoom.disable()
  } else {
    map.doubleClickZoom.enable()
  }

  const basemapConfig = BASEMAP_PROVIDER_REGISTRY[state.basemap]
  const hasRaster = Boolean(basemapConfig.gibsLayerId)

  if (map.getLayer('country-thematic-fill')) {
    map.setPaintProperty(
      'country-thematic-fill',
      'fill-color',
      buildCountryColorExpression(state.activeLayer, state.syntheticPreviewEnabled, state.basemap),
    )
    map.setPaintProperty(
      'country-thematic-fill',
      'fill-opacity',
      state.activeLayer &&
        state.activeLayer.visible &&
        state.syntheticPreviewEnabled &&
        state.activeLayer.layer.isSyntheticPreview
        ? state.activeLayer.opacity
        : hasRaster ? 0 : 1,
    )
  }

  const selectedIso = state.selectedCountry?.isoA3 ?? null
  if (map.getLayer('country-selected-fill')) {
    map.setPaintProperty(
      'country-selected-fill',
      'fill-color',
      selectedIso
        ? ['case', ['==', ['get', 'isoA3'], selectedIso], 'rgba(21, 155, 145, 0.28)', 'rgba(0, 0, 0, 0)']
        : ['literal', 'rgba(0,0,0,0)'],
    )
  }
  if (map.getLayer('country-selected-outline')) {
    map.setPaintProperty(
      'country-selected-outline',
      'line-width',
      selectedIso ? ['case', ['==', ['get', 'isoA3'], selectedIso], 2.2, 0] : 0,
    )
  }

  const gratVis = state.showGraticules ? 'visible' : 'none'
  if (map.getLayer('graticule-grid-lines')) map.setLayoutProperty('graticule-grid-lines', 'visibility', gratVis)
  if (map.getLayer('graticule-equator-line')) map.setLayoutProperty('graticule-equator-line', 'visibility', gratVis)

  const borderVis = state.showBorders ? 'visible' : 'none'
  if (map.getLayer('country-borders')) map.setLayoutProperty('country-borders', 'visibility', borderVis)
  if (map.getLayer('coastline-stroke')) map.setLayoutProperty('coastline-stroke', 'visibility', borderVis)

  const regionVis = state.showRegionBoundaries ? 'visible' : 'none'
  if (map.getLayer('terra-region-aois-fill')) map.setLayoutProperty('terra-region-aois-fill', 'visibility', regionVis)
  if (map.getLayer('terra-region-aois-line')) map.setLayoutProperty('terra-region-aois-line', 'visibility', regionVis)

  const aoiSource = map.getSource('terra-user-aois') as GeoJSONSource | undefined
  aoiSource?.setData({ type: 'FeatureCollection', features: [...state.aois] })

  const draftSource = map.getSource('terra-draft-geometry') as GeoJSONSource | undefined
  if (draftSource) {
    const draftFeatures: Feature<Geometry>[] = []
    if (state.draftVertices.length > 0) {
      if (state.interactionMode === 'draw-rectangle' && state.draftHoverPoint) {
        draftFeatures.push({
          type: 'Feature',
          properties: {},
          geometry: createRectangleGeometry(state.draftVertices[0], state.draftHoverPoint),
        })
      } else {
        const lineCoords = state.draftHoverPoint ? [...state.draftVertices, state.draftHoverPoint] : [...state.draftVertices]
        if (lineCoords.length >= 3 && state.interactionMode === 'draw-polygon') {
          draftFeatures.push({ type: 'Feature', properties: {}, geometry: createPolygonGeometry(lineCoords) })
        } else if (lineCoords.length >= 2) {
          draftFeatures.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: lineCoords } })
        }
        for (const vertex of state.draftVertices) {
          draftFeatures.push({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: vertex } })
        }
      }
    }
    draftSource.setData({ type: 'FeatureCollection', features: draftFeatures })
  }

  const inspectSource = map.getSource('terra-inspect-point') as GeoJSONSource | undefined
  inspectSource?.setData({
    type: 'FeatureCollection',
    features: state.inspectedPoint
      ? [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [state.inspectedPoint.lon, state.inspectedPoint.lat] } }]
      : [],
  })
}

function isPointVisibleOnGlobe(map: MapLibreMap, lon: number, lat: number): boolean {
  const center = map.getCenter()
  const toRad = Math.PI / 180
  const lat1 = center.lat * toRad
  const lon1 = center.lng * toRad
  const lat2 = lat * toRad
  const lon2 = lon * toRad
  return Math.sin(lat1) * Math.sin(lat2) + Math.cos(lat1) * Math.cos(lat2) * Math.cos(lon2 - lon1) > 0.12
}

export function renderMapLibreLabels(
  map: MapLibreMap | null,
  container: HTMLDivElement | null,
  state: MapRenderState | null,
): void {
  if (!map || !container || !state) return
  if (!state.showLabels) {
    container.innerHTML = ''
    return
  }

  const width = container.clientWidth
  const height = container.clientHeight
  const zoom = map.getZoom()
  const hasRaster = Boolean(BASEMAP_PROVIDER_REGISTRY[state.basemap].gibsLayerId)
  const labelColor = hasRaster ? 'rgba(245,250,252,0.9)' : '#365058'
  const geoColor = hasRaster ? 'rgba(220,235,242,0.75)' : '#7f939c'

  const elements: string[] = []
  if (zoom <= 3.3) {
    for (const item of CONTINENT_AND_OCEAN_LABELS) {
      if (state.projection === 'globe' && !isPointVisibleOnGlobe(map, item.longitude, item.latitude)) continue
      const pt = map.project([item.longitude, item.latitude])
      if (pt.x < 24 || pt.x > width - 24 || pt.y < 16 || pt.y > height - 16) continue
      elements.push(
        `<span style="position:absolute;left:${Math.round(pt.x)}px;top:${Math.round(pt.y)}px;transform:translate(-50%,-50%);font-size:9px;font-weight:500;letter-spacing:0.75px;color:${geoColor};white-space:nowrap;text-shadow:${
          hasRaster ? '0 1px 2px rgba(0,0,0,0.65)' : '0 1px 2px rgba(255,255,255,0.9)'
        }">${item.text}</span>`,
      )
    }
  }

  const maxRank = zoom >= 2.5 ? 3 : zoom >= 1.5 ? 2 : 1
  for (const country of MAJOR_COUNTRY_LABELS) {
    const isSelected = state.selectedCountry?.isoA3 === country.isoA3
    const isHovered = state.hoveredCountryIso === country.isoA3
    if (country.labelRank > maxRank && !isSelected && !isHovered) continue
    if (state.projection === 'globe' && !isPointVisibleOnGlobe(map, country.longitude, country.latitude)) continue
    const pt = map.project([country.longitude, country.latitude])
    if (pt.x < 24 || pt.x > width - 24 || pt.y < 16 || pt.y > height - 16) continue
    const bg = isSelected
      ? 'rgba(231,244,242,0.96)'
      : hasRaster ? 'rgba(13,28,39,0.55)' : 'rgba(255,255,255,0.68)'
    const color = isSelected ? '#0e4d4a' : labelColor
    elements.push(
      `<span style="position:absolute;left:${Math.round(pt.x)}px;top:${Math.round(pt.y)}px;transform:translate(-50%,-50%);font-size:8.5px;font-weight:${
        isSelected || isHovered ? 600 : 500
      };color:${color};background:${bg};padding:1px 4px;border-radius:3px;white-space:nowrap">${country.name}</span>`,
    )
  }

  container.innerHTML = elements.join('')
}
