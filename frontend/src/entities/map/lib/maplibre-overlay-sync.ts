import type { Feature, Geometry } from 'geojson'
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl'
import { createPolygonGeometry, createRectangleGeometry } from '../../../shared/lib/geojson-utils'
import type { MapRenderState } from '../model/map-renderer'
import { buildDatasetBboxGeoJson, resolveScienceRasterConfig } from './maplibre-style-builder'

const ACTIVE_RASTER_URL_BY_MAP = new WeakMap<MapLibreMap, string | null>()

function syncScienceRasterSource(map: MapLibreMap, state: MapRenderState): void {
  const nextRaster = resolveScienceRasterConfig(state.activeLayer, state.selectedDate)
  const nextUrl = nextRaster?.tileUrl ?? null
  const prevUrl = ACTIVE_RASTER_URL_BY_MAP.get(map) ?? null
  const hasLayer = Boolean(map.getLayer('active-science-raster-layer'))
  const hasSource = Boolean(map.getSource('active-science-raster'))

  if (!nextRaster || !nextUrl) {
    if (hasLayer) map.removeLayer('active-science-raster-layer')
    if (hasSource) map.removeSource('active-science-raster')
    ACTIVE_RASTER_URL_BY_MAP.set(map, null)
    return
  }

  if (hasLayer && hasSource && prevUrl === nextUrl) {
    map.setPaintProperty('active-science-raster-layer', 'raster-opacity', state.activeLayer?.opacity ?? 0.85)
    return
  }

  if (hasLayer) map.removeLayer('active-science-raster-layer')
  if (hasSource) map.removeSource('active-science-raster')

  map.addSource('active-science-raster', {
    type: 'raster',
    tiles: [nextUrl],
    tileSize: 256,
    minzoom: 0,
    maxzoom: 18,
    ...(nextRaster.bounds ? { bounds: nextRaster.bounds } : {}),
    attribution: state.activeLayer?.layer.attribution ?? 'NASA Earth Observations via TERRA',
  })

  const beforeId = map.getLayer('graticule-grid-lines')
    ? 'graticule-grid-lines'
    : map.getLayer('ofm-boundary-country')
      ? 'ofm-boundary-country'
      : undefined

  map.addLayer(
    {
      id: 'active-science-raster-layer',
      type: 'raster',
      source: 'active-science-raster',
      paint: {
        'raster-opacity': state.activeLayer?.opacity ?? 0.85,
        'raster-resampling': 'nearest',
        'raster-fade-duration': 0,
      },
    },
    beforeId,
  )
  ACTIVE_RASTER_URL_BY_MAP.set(map, nextUrl)
}

export function syncMapLibreLayersAndSources(map: MapLibreMap, state: MapRenderState): void {
  if (state.interactionMode === 'draw-polygon') {
    map.doubleClickZoom.disable()
  } else {
    map.doubleClickZoom.enable()
  }

  syncScienceRasterSource(map, state)

  const bboxSource = map.getSource('terra-dataset-bbox') as GeoJSONSource | undefined
  bboxSource?.setData(buildDatasetBboxGeoJson(state.activeLayer?.layer.datasetBbox))

  const selectedIso = state.selectedCountry?.isoA3 ?? null
  if (map.getLayer('country-selected-fill')) {
    map.setPaintProperty(
      'country-selected-fill',
      'fill-color',
      selectedIso
        ? ['case', ['==', ['get', 'isoA3'], selectedIso], 'rgba(21, 155, 145, 0.24)', 'rgba(0, 0, 0, 0)']
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
  if (map.getLayer('ofm-boundary-sub')) map.setLayoutProperty('ofm-boundary-sub', 'visibility', borderVis)
  if (map.getLayer('ofm-boundary-country')) map.setLayoutProperty('ofm-boundary-country', 'visibility', borderVis)

  const labelVis = state.showLabels ? 'visible' : 'none'
  for (const layerId of [
    'ofm-label-water',
    'ofm-label-place-minor',
    'ofm-label-place-city',
    'ofm-label-place-state',
    'ofm-label-place-country',
  ]) {
    if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', labelVis)
  }
  if (map.getLayer('ofm-label-road')) {
    map.setLayoutProperty(
      'ofm-label-road',
      'visibility',
      state.showLabels && state.basemap === 'scientific-light' ? 'visible' : 'none',
    )
  }

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
        const lineCoords = state.draftHoverPoint
          ? [...state.draftVertices, state.draftHoverPoint]
          : [...state.draftVertices]
        if (lineCoords.length >= 3 && state.interactionMode === 'draw-polygon') {
          draftFeatures.push({
            type: 'Feature',
            properties: {},
            geometry: createPolygonGeometry(lineCoords),
          })
        } else if (lineCoords.length >= 2) {
          draftFeatures.push({
            type: 'Feature',
            properties: {},
            geometry: { type: 'LineString', coordinates: lineCoords },
          })
        }
        for (const vertex of state.draftVertices) {
          draftFeatures.push({
            type: 'Feature',
            properties: {},
            geometry: { type: 'Point', coordinates: vertex },
          })
        }
      }
    }
    draftSource.setData({ type: 'FeatureCollection', features: draftFeatures })
  }

  const inspectSource = map.getSource('terra-inspect-point') as GeoJSONSource | undefined
  inspectSource?.setData({
    type: 'FeatureCollection',
    features: state.inspectedPoint
      ? [
          {
            type: 'Feature',
            properties: {},
            geometry: {
              type: 'Point',
              coordinates: [state.inspectedPoint.lon, state.inspectedPoint.lat],
            },
          },
        ]
      : [],
  })
}

export function renderMapLibreLabels(container: HTMLDivElement | null): void {
  if (container && container.innerHTML !== '') {
    container.innerHTML = ''
  }
}
