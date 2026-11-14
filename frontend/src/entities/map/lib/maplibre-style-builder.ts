import type { FeatureCollection, Geometry } from 'geojson'
import type { ExpressionSpecification, StyleSpecification } from 'maplibre-gl'
import {
  BASEMAP_PROVIDER_REGISTRY,
  buildGibsMercatorTileUrl,
  GEOSPATIAL_PUBLIC_CONFIG,
} from '../../../shared/config/geospatial'
import type { BasemapId } from '../../../shared/types/geospatial'
import {
  buildGraticuleGeoJson,
  REGION_AOI_GEOJSON,
} from '../../../widgets/world-map/config/cartographic-data'
import type { LayerRenderConfig, MapRenderState } from '../model/map-renderer'

const EMPTY_FC: FeatureCollection<Geometry> = {
  type: 'FeatureCollection',
  features: [],
}

export function buildCountryColorExpression(
  activeLayer: LayerRenderConfig | null,
  syntheticPreviewEnabled: boolean,
  basemap: BasemapId,
): ExpressionSpecification {
  const basemapConfig = BASEMAP_PROVIDER_REGISTRY[basemap]
  const hasRaster = Boolean(basemapConfig.gibsLayerId)

  if (
    !activeLayer ||
    !activeLayer.visible ||
    !syntheticPreviewEnabled ||
    !activeLayer.layer.isSyntheticPreview ||
    !activeLayer.layer.previewPropertyKey
  ) {
    return ['literal', hasRaster ? 'rgba(0,0,0,0)' : basemapConfig.landFallbackColor] as ExpressionSpecification
  }

  const expr: unknown[] = [
    'interpolate',
    ['linear'],
    ['coalesce', ['get', activeLayer.layer.previewPropertyKey], 0],
  ]

  const minBound = activeLayer.minValue
  const maxBound = activeLayer.maxValue
  const stops = activeLayer.layer.colorRamp
  for (let i = 0; i < stops.length; i++) {
    const t = stops.length > 1 ? i / (stops.length - 1) : 0
    expr.push(minBound + t * (maxBound - minBound), stops[i].color)
  }

  return expr as ExpressionSpecification
}

export function buildMapLibreStyle(state: MapRenderState): StyleSpecification {
  const basemapConfig = BASEMAP_PROVIDER_REGISTRY[state.basemap]
  const tileUrl = buildGibsMercatorTileUrl(state.basemap, state.selectedDate)
  const graticules = buildGraticuleGeoJson()

  const sources: StyleSpecification['sources'] = {
    'ne-graticules': { type: 'geojson', data: graticules },
    'ne-countries': { type: 'geojson', data: GEOSPATIAL_PUBLIC_CONFIG.naturalEarthCountriesUrl },
    'ne-coastline': { type: 'geojson', data: GEOSPATIAL_PUBLIC_CONFIG.naturalEarthCoastlineUrl },
    'terra-region-aois': { type: 'geojson', data: REGION_AOI_GEOJSON },
    'terra-user-aois': { type: 'geojson', data: EMPTY_FC },
    'terra-draft-geometry': { type: 'geojson', data: EMPTY_FC },
    'terra-inspect-point': { type: 'geojson', data: EMPTY_FC },
  }

  const layers: StyleSpecification['layers'] = [
    {
      id: 'ocean-background',
      type: 'background',
      paint: { 'background-color': basemapConfig.backgroundOceanColor },
    },
  ]

  if (tileUrl) {
    sources['gibs-basemap'] = {
      type: 'raster',
      tiles: [tileUrl],
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
  }

  layers.push(
    {
      id: 'graticule-grid-lines',
      type: 'line',
      source: 'ne-graticules',
      filter: ['==', ['get', 'isEquator'], false],
      layout: { visibility: state.showGraticules ? 'visible' : 'none' },
      paint: { 'line-color': tileUrl ? 'rgba(255,255,255,0.2)' : '#dbe6e9', 'line-width': 0.8 },
    },
    {
      id: 'graticule-equator-line',
      type: 'line',
      source: 'ne-graticules',
      filter: ['==', ['get', 'isEquator'], true],
      layout: { visibility: state.showGraticules ? 'visible' : 'none' },
      paint: {
        'line-color': tileUrl ? 'rgba(255,255,255,0.45)' : '#bfd2d7',
        'line-width': 1.15,
        'line-dasharray': [4, 3],
      },
    },
    {
      id: 'country-thematic-fill',
      type: 'fill',
      source: 'ne-countries',
      paint: {
        'fill-color': buildCountryColorExpression(state.activeLayer, state.syntheticPreviewEnabled, state.basemap),
        'fill-opacity':
          state.activeLayer &&
          state.activeLayer.visible &&
          state.syntheticPreviewEnabled &&
          state.activeLayer.layer.isSyntheticPreview
            ? state.activeLayer.opacity
            : tileUrl ? 0 : 1,
      },
    },
    {
      id: 'country-hover-fill',
      type: 'fill',
      source: 'ne-countries',
      paint: {
        'fill-color': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          'rgba(21, 155, 145, 0.22)',
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
      id: 'coastline-stroke',
      type: 'line',
      source: 'ne-coastline',
      layout: { visibility: state.showBorders ? 'visible' : 'none' },
      paint: { 'line-color': basemapConfig.borderColor, 'line-width': 0.85 },
    },
    {
      id: 'country-borders',
      type: 'line',
      source: 'ne-countries',
      layout: { visibility: state.showBorders ? 'visible' : 'none' },
      paint: { 'line-color': basemapConfig.borderColor, 'line-width': 0.8 },
    },
    {
      id: 'country-selected-outline',
      type: 'line',
      source: 'ne-countries',
      paint: { 'line-color': '#0e4d4a', 'line-width': 0 },
    },
    {
      id: 'terra-region-aois-fill',
      type: 'fill',
      source: 'terra-region-aois',
      layout: { visibility: state.showRegionBoundaries ? 'visible' : 'none' },
      paint: { 'fill-color': 'rgba(21, 155, 145, 0.08)' },
    },
    {
      id: 'terra-region-aois-line',
      type: 'line',
      source: 'terra-region-aois',
      layout: { visibility: state.showRegionBoundaries ? 'visible' : 'none' },
      paint: { 'line-color': '#159b91', 'line-width': 1.2, 'line-dasharray': [4, 3] },
    },
    {
      id: 'terra-user-aois-fill',
      type: 'fill',
      source: 'terra-user-aois',
      paint: {
        'fill-color': [
          'case',
          ['==', ['get', 'role'], 'regionB'],
          'rgba(49, 147, 206, 0.22)',
          'rgba(21, 155, 145, 0.22)',
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
      paint: { 'circle-radius': 4, 'circle-color': '#ffffff', 'circle-stroke-color': '#159b91', 'circle-stroke-width': 2 },
    },
    {
      id: 'terra-inspect-halo',
      type: 'circle',
      source: 'terra-inspect-point',
      paint: { 'circle-radius': 10, 'circle-color': 'rgba(21, 155, 145, 0.18)', 'circle-stroke-color': '#159b91', 'circle-stroke-width': 1.5 },
    },
    {
      id: 'terra-inspect-core',
      type: 'circle',
      source: 'terra-inspect-point',
      paint: { 'circle-radius': 3.8, 'circle-color': '#159b91', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5 },
    },
  )

  return { version: 8, name: 'TERRA MapLibre Explorer Style', sources, layers }
}
