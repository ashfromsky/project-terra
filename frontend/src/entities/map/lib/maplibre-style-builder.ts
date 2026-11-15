import type { FeatureCollection, Geometry } from 'geojson'
import type { LayerSpecification, StyleSpecification } from 'maplibre-gl'
import { buildApiUrl } from '../../../shared/api/client'
import { buildLayerTileUrlTemplate, resolveLayerEffectiveDate } from '../../../shared/api/layers'
import {
  BASEMAP_PROVIDER_REGISTRY,
  buildGibsMercatorTileUrl,
  GEOSPATIAL_PUBLIC_CONFIG,
} from '../../../shared/config/geospatial'
import { buildGraticuleGeoJson } from '../../../widgets/world-map/config/cartographic-data'
import type { LayerRenderConfig, MapRenderState } from '../model/map-renderer'

const EMPTY_FC: FeatureCollection<Geometry> = {
  type: 'FeatureCollection',
  features: [],
}

export function resolveScienceRasterConfig(
  activeLayer: LayerRenderConfig | null,
  selectedDate: string,
): {
  tileUrl: string
  bounds?: [number, number, number, number]
  minzoom?: number
  maxzoom?: number
} | null {
  if (!activeLayer || !activeLayer.visible) {
    return null
  }
  const hasExternalTemplate = Boolean(
    activeLayer.layer.tileSource?.urlTemplate &&
      (activeLayer.layer.tileSource.urlTemplate.startsWith('http://') ||
        activeLayer.layer.tileSource.urlTemplate.startsWith('https://')),
  )
  const isAvailableLocally =
    (activeLayer.layer.availabilityStatus === 'connected' ||
      activeLayer.layer.availabilityStatus === 'preview') &&
    activeLayer.layer.tileSource.isConnected

  if (!hasExternalTemplate && !isAvailableLocally) {
    return null
  }
  const effectiveDate = resolveLayerEffectiveDate(activeLayer.layer, selectedDate)
  let tileUrl: string
  if (hasExternalTemplate && activeLayer.layer.tileSource.urlTemplate) {
    const rawTemplate = activeLayer.layer.tileSource.urlTemplate
    const withTime = rawTemplate
      .replace('{time}', effectiveDate || 'default')
      .replace('{timestamp}', effectiveDate || 'default')
    tileUrl =
      withTime.startsWith('http://') || withTime.startsWith('https://')
        ? withTime
        : buildApiUrl(withTime)
  } else {
    // Always build an absolute, date-aware tile URL. MapLibre does not reliably
    // expand relative raster templates after the first style load.
    tileUrl = buildLayerTileUrlTemplate(activeLayer.layer.id, {
      timestamp: effectiveDate,
      vmin: activeLayer.minValue,
      vmax: activeLayer.maxValue,
      datasetId: activeLayer.layer.activeDatasetId ?? undefined,
    })
  }
  const rawBounds = activeLayer.layer.datasetBbox
  const bounds: [number, number, number, number] | undefined =
    rawBounds && rawBounds.length === 4
      ? [rawBounds[0], rawBounds[1], rawBounds[2], rawBounds[3]]
      : undefined
  return {
    tileUrl,
    bounds,
    minzoom: (activeLayer.layer.tileSource as { minZoom?: number }).minZoom ?? 0,
    maxzoom: (activeLayer.layer.tileSource as { maxZoom?: number }).maxZoom ?? 18,
  }
}

export function buildDatasetBboxGeoJson(
  ..._args: unknown[]
): FeatureCollection<Geometry> {
  void _args
  return EMPTY_FC
}

export function buildMapLibreStyle(state: MapRenderState): StyleSpecification {
  const basemapConfig = BASEMAP_PROVIDER_REGISTRY[state.basemap]
  const gibsTileUrl = buildGibsMercatorTileUrl(state.basemap, state.selectedDate)
  const isGibsBasemap = Boolean(gibsTileUrl)
  const scienceRaster = resolveScienceRasterConfig(state.activeLayer, state.selectedDate)
  const graticules = buildGraticuleGeoJson()

  const sources: StyleSpecification['sources'] = {
    openmaptiles: {
      type: 'vector',
      url: GEOSPATIAL_PUBLIC_CONFIG.openFreeMapTileJsonUrl,
      attribution: '© OpenFreeMap © OpenMapTiles · Data from OpenStreetMap',
    },
    'ne-graticules': { type: 'geojson', data: graticules },
    'ne-countries': { type: 'geojson', data: GEOSPATIAL_PUBLIC_CONFIG.naturalEarthCountriesUrl },
    'terra-dataset-bbox': {
      type: 'geojson',
      data: EMPTY_FC,
    },
    'terra-user-aois': { type: 'geojson', data: EMPTY_FC },
    'terra-draft-geometry': { type: 'geojson', data: EMPTY_FC },
    'terra-inspect-point': { type: 'geojson', data: EMPTY_FC },
  }

  const layers: LayerSpecification[] = [
    {
      id: 'ocean-background',
      type: 'background',
      paint: { 'background-color': isGibsBasemap ? basemapConfig.backgroundOceanColor : '#f2f4f0' },
    },
  ]

  if (gibsTileUrl) {
    sources['gibs-basemap'] = {
      type: 'raster',
      tiles: [gibsTileUrl],
      tileSize: 256,
      minzoom: basemapConfig.minZoom,
      maxzoom: basemapConfig.maxZoom,
      attribution: basemapConfig.attribution,
    }
    layers.push({
      id: 'gibs-basemap-layer',
      type: 'raster',
      source: 'gibs-basemap',
      paint: { 'raster-opacity': 1, 'raster-fade-duration': 150 },
    })
  } else {
    layers.push(
      {
        id: 'ofm-landcover',
        type: 'fill',
        source: 'openmaptiles',
        'source-layer': 'landcover',
        paint: {
          'fill-color': [
            'match',
            ['get', 'class'],
            ['wood', 'forest'],
            '#dce9dc',
            'grass',
            '#e6efe2',
            'farmland',
            '#eeefe3',
            'sand',
            '#f2ece0',
            'wetland',
            '#d9ebe6',
            'ice',
            '#eef4f7',
            '#ecefe9',
          ],
          'fill-opacity': 0.85,
        },
      },
      {
        id: 'ofm-park',
        type: 'fill',
        source: 'openmaptiles',
        'source-layer': 'park',
        paint: { 'fill-color': '#d7e8d8', 'fill-opacity': 0.7 },
      },
      {
        id: 'ofm-landuse',
        type: 'fill',
        source: 'openmaptiles',
        'source-layer': 'landuse',
        paint: {
          'fill-color': [
            'match',
            ['get', 'class'],
            'residential',
            '#e7eaec',
            ['industrial', 'commercial'],
            '#e3e6e9',
            '#eceeed',
          ],
          'fill-opacity': 0.65,
        },
      },
      {
        id: 'ofm-water',
        type: 'fill',
        source: 'openmaptiles',
        'source-layer': 'water',
        paint: { 'fill-color': '#cae0ed' },
      },
      {
        id: 'ofm-waterway',
        type: 'line',
        source: 'openmaptiles',
        'source-layer': 'waterway',
        paint: {
          'line-color': '#93bfd7',
          'line-width': [
            'interpolate',
            ['linear'],
            ['zoom'],
            5,
            0.6,
            10,
            1.4,
            15,
            2.6,
          ],
        },
      },
      {
        id: 'ofm-building',
        type: 'fill',
        source: 'openmaptiles',
        'source-layer': 'building',
        minzoom: 13,
        paint: { 'fill-color': '#dde1e4', 'fill-outline-color': '#cfd5d9', 'fill-opacity': 0.8 },
      },
      {
        id: 'ofm-aeroway',
        type: 'line',
        source: 'openmaptiles',
        'source-layer': 'aeroway',
        minzoom: 10,
        paint: { 'line-color': '#d5dade', 'line-width': 2 },
      },
      {
        id: 'ofm-road-rail',
        type: 'line',
        source: 'openmaptiles',
        'source-layer': 'transportation',
        minzoom: 8,
        filter: ['==', ['get', 'class'], 'rail'],
        paint: { 'line-color': '#bcc5cb', 'line-width': 1, 'line-dasharray': [3, 2] },
      },
      {
        id: 'ofm-road-minor',
        type: 'line',
        source: 'openmaptiles',
        'source-layer': 'transportation',
        minzoom: 11,
        filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'track']]],
        paint: {
          'line-color': '#ffffff',
          'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.7, 16, 4.5],
        },
      },
      {
        id: 'ofm-road-secondary',
        type: 'line',
        source: 'openmaptiles',
        'source-layer': 'transportation',
        minzoom: 8,
        filter: ['in', ['get', 'class'], ['literal', ['secondary', 'tertiary']]],
        paint: {
          'line-color': '#f9f8f3',
          'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 15, 5.5],
        },
      },
      {
        id: 'ofm-road-primary',
        type: 'line',
        source: 'openmaptiles',
        'source-layer': 'transportation',
        minzoom: 6,
        filter: ['in', ['get', 'class'], ['literal', ['primary', 'trunk']]],
        paint: {
          'line-color': '#f5e6bf',
          'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.7, 14, 5.2],
        },
      },
      {
        id: 'ofm-road-motorway',
        type: 'line',
        source: 'openmaptiles',
        'source-layer': 'transportation',
        minzoom: 4,
        filter: ['==', ['get', 'class'], 'motorway'],
        paint: {
          'line-color': '#ecc898',
          'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.7, 14, 6.2],
        },
      },
    )
  }

  if (scienceRaster) {
    sources['active-science-raster'] = {
      type: 'raster',
      tiles: [scienceRaster.tileUrl],
      tileSize: 256,
      minzoom: scienceRaster.minzoom ?? 0,
      maxzoom: scienceRaster.maxzoom ?? 18,
      ...(scienceRaster.bounds ? { bounds: scienceRaster.bounds } : {}),
      attribution: state.activeLayer?.layer.attribution ?? 'NASA Earth Observations via TERRA',
    }
    layers.push({
      id: 'active-science-raster-layer',
      type: 'raster',
      source: 'active-science-raster',
      paint: {
        'raster-opacity': state.activeLayer?.opacity ?? 0.85,
        'raster-resampling': 'nearest',
        'raster-fade-duration': 0,
      },
    })
  }

  layers.push(
    {
      id: 'graticule-grid-lines',
      type: 'line',
      source: 'ne-graticules',
      filter: ['==', ['get', 'isEquator'], false],
      layout: { visibility: state.showGraticules ? 'visible' : 'none' },
      paint: {
        'line-color': isGibsBasemap ? 'rgba(255,255,255,0.2)' : 'rgba(130, 152, 162, 0.25)',
        'line-width': 0.75,
      },
    },
    {
      id: 'graticule-equator-line',
      type: 'line',
      source: 'ne-graticules',
      filter: ['==', ['get', 'isEquator'], true],
      layout: { visibility: state.showGraticules ? 'visible' : 'none' },
      paint: {
        'line-color': isGibsBasemap ? 'rgba(255,255,255,0.45)' : 'rgba(98, 126, 138, 0.45)',
        'line-width': 1.1,
        'line-dasharray': [4, 3],
      },
    },
    {
      id: 'country-hit-fill',
      type: 'fill',
      source: 'ne-countries',
      paint: { 'fill-color': 'rgba(0, 0, 0, 0)' },
    },
    {
      id: 'country-hover-fill',
      type: 'fill',
      source: 'ne-countries',
      paint: {
        'fill-color': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          'rgba(21, 155, 145, 0.16)',
          'rgba(0, 0, 0, 0)',
        ],
      },
    },
    {
      id: 'country-selected-fill',
      type: 'fill',
      source: 'ne-countries',
      paint: { 'fill-color': 'rgba(21, 155, 145, 0)' },
    },
    {
      id: 'ofm-boundary-sub',
      type: 'line',
      source: 'openmaptiles',
      'source-layer': 'boundary',
      filter: ['all', ['!=', ['get', 'maritime'], 1], ['>=', ['get', 'admin_level'], 4]],
      layout: { visibility: state.showBorders ? 'visible' : 'none' },
      paint: {
        'line-color': isGibsBasemap ? 'rgba(255, 255, 255, 0.32)' : 'rgba(125, 142, 150, 0.48)',
        'line-width': 0.75,
        'line-dasharray': [3, 2],
      },
    },
    {
      id: 'ofm-boundary-country',
      type: 'line',
      source: 'openmaptiles',
      'source-layer': 'boundary',
      filter: ['all', ['!=', ['get', 'maritime'], 1], ['==', ['get', 'admin_level'], 2]],
      layout: { visibility: state.showBorders ? 'visible' : 'none' },
      paint: {
        'line-color': isGibsBasemap ? 'rgba(255, 255, 255, 0.72)' : '#7f939d',
        'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.7, 6, 1.4, 12, 2.0],
      },
    },
    {
      id: 'country-selected-outline',
      type: 'line',
      source: 'ne-countries',
      paint: { 'line-color': '#0e4d4a', 'line-width': 0 },
    },
    {
      id: 'terra-dataset-bbox-line',
      type: 'line',
      source: 'terra-dataset-bbox',
      layout: { visibility: 'none' },
      paint: { 'line-color': '#159b91', 'line-width': 0 },
    },
    {
      id: 'terra-user-aois-fill',
      type: 'fill',
      source: 'terra-user-aois',
      paint: {
        'fill-color': [
          'case',
          ['==', ['get', 'role'], 'regionB'],
          'rgba(49, 147, 206, 0.2)',
          'rgba(21, 155, 145, 0.2)',
        ],
      },
    },
    {
      id: 'terra-user-aois-line',
      type: 'line',
      source: 'terra-user-aois',
      paint: {
        'line-color': ['case', ['==', ['get', 'role'], 'regionB'], '#3193ce', '#159b91'],
        'line-width': 2.1,
      },
    },
    {
      id: 'terra-draft-fill',
      type: 'fill',
      source: 'terra-draft-geometry',
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: { 'fill-color': 'rgba(21, 155, 145, 0.16)' },
    },
    {
      id: 'terra-draft-line',
      type: 'line',
      source: 'terra-draft-geometry',
      paint: { 'line-color': '#159b91', 'line-width': 2, 'line-dasharray': [4, 3] },
    },
    {
      id: 'terra-draft-points',
      type: 'circle',
      source: 'terra-draft-geometry',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': 4,
        'circle-color': '#ffffff',
        'circle-stroke-color': '#159b91',
        'circle-stroke-width': 2,
      },
    },
    {
      id: 'terra-inspect-halo',
      type: 'circle',
      source: 'terra-inspect-point',
      paint: {
        'circle-radius': 10,
        'circle-color': 'rgba(21, 155, 145, 0.18)',
        'circle-stroke-color': '#159b91',
        'circle-stroke-width': 1.5,
      },
    },
    {
      id: 'terra-inspect-core',
      type: 'circle',
      source: 'terra-inspect-point',
      paint: {
        'circle-radius': 3.8,
        'circle-color': '#159b91',
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1.5,
      },
    },
    {
      id: 'ofm-label-water',
      type: 'symbol',
      source: 'openmaptiles',
      'source-layer': 'water_name',
      layout: {
        visibility: state.showLabels ? 'visible' : 'none',
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Italic'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 2, 10, 8, 12],
      },
      paint: {
        'text-color': isGibsBasemap ? '#b9def0' : '#4a7a96',
        'text-halo-color': isGibsBasemap ? 'rgba(9, 20, 31, 0.8)' : 'rgba(255, 255, 255, 0.85)',
        'text-halo-width': 1.2,
      },
    },
    {
      id: 'ofm-label-road',
      type: 'symbol',
      source: 'openmaptiles',
      'source-layer': 'transportation_name',
      minzoom: 12,
      layout: {
        visibility: state.showLabels && !isGibsBasemap ? 'visible' : 'none',
        'symbol-placement': 'line',
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Regular'],
        'text-size': 10,
      },
      paint: {
        'text-color': '#495a61',
        'text-halo-color': '#ffffff',
        'text-halo-width': 1.4,
      },
    },
    {
      id: 'ofm-label-place-minor',
      type: 'symbol',
      source: 'openmaptiles',
      'source-layer': 'place',
      minzoom: 7,
      filter: ['in', ['get', 'class'], ['literal', ['town', 'village', 'suburb', 'hamlet']]],
      layout: {
        visibility: state.showLabels ? 'visible' : 'none',
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Regular'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 7, 10, 14, 13],
      },
      paint: {
        'text-color': isGibsBasemap ? '#f1f6f9' : '#354952',
        'text-halo-color': isGibsBasemap ? 'rgba(9, 20, 31, 0.85)' : 'rgba(255, 255, 255, 0.9)',
        'text-halo-width': 1.4,
      },
    },
    {
      id: 'ofm-label-place-city',
      type: 'symbol',
      source: 'openmaptiles',
      'source-layer': 'place',
      minzoom: 3,
      filter: ['==', ['get', 'class'], 'city'],
      layout: {
        visibility: state.showLabels ? 'visible' : 'none',
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Bold'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 3, 10, 10, 14],
      },
      paint: {
        'text-color': isGibsBasemap ? '#ffffff' : '#1f333b',
        'text-halo-color': isGibsBasemap ? 'rgba(9, 20, 31, 0.88)' : 'rgba(255, 255, 255, 0.92)',
        'text-halo-width': 1.5,
      },
    },
    {
      id: 'ofm-label-place-state',
      type: 'symbol',
      source: 'openmaptiles',
      'source-layer': 'place',
      minzoom: 4,
      maxzoom: 8,
      filter: ['==', ['get', 'class'], 'state'],
      layout: {
        visibility: state.showLabels ? 'visible' : 'none',
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Regular'],
        'text-size': 10,
      },
      paint: {
        'text-color': isGibsBasemap ? 'rgba(235, 245, 250, 0.82)' : '#637882',
        'text-halo-color': isGibsBasemap ? 'rgba(9, 20, 31, 0.78)' : 'rgba(255, 255, 255, 0.85)',
        'text-halo-width': 1.2,
      },
    },
    {
      id: 'ofm-label-place-country',
      type: 'symbol',
      source: 'openmaptiles',
      'source-layer': 'place',
      minzoom: 1,
      maxzoom: 6,
      filter: ['==', ['get', 'class'], 'country'],
      layout: {
        visibility: state.showLabels ? 'visible' : 'none',
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Bold'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 1, 9.5, 5, 13],
      },
      paint: {
        'text-color': isGibsBasemap ? '#f7fbfc' : '#263d46',
        'text-halo-color': isGibsBasemap ? 'rgba(9, 20, 31, 0.85)' : 'rgba(255, 255, 255, 0.9)',
        'text-halo-width': 1.5,
      },
    },
  )

  return {
    version: 8,
    name: 'TERRA OpenFreeMap & Scientific Raster Style',
    glyphs: GEOSPATIAL_PUBLIC_CONFIG.openFreeMapGlyphsUrl,
    sources,
    layers,
  }
}
