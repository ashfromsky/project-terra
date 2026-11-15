import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from 'maplibre-gl'
import { buildLayerTileUrlTemplate, resolveLayerEffectiveDate } from '../../../shared/api/layers'
import { GEOSPATIAL_PUBLIC_CONFIG } from '../../../shared/config/geospatial'
import type {
  MapLayerVisibility,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'
import type { MapLayerDefinition } from '../../../shared/types/geospatial'
import type { ThematicLayerDefinition } from '../model/types'
import { buildGraticuleGeoJson } from './cartographic-data'

export const CARTOGRAPHIC_PROJECTION_SPEC = {
  renderedProjection: 'Web Mercator (OpenFreeMap Vector · EPSG:3857)',
  targetProjection: 'EPSG:3857 · Live backend raster overlays',
  datasetName: 'OpenFreeMap OpenMapTiles + Natural Earth 110m',
  note: 'Interactive OpenFreeMap vector cartography with nearest-neighbor backend COG raster tiles',
} as const

export const VARIABLE_TO_LAYER_ID: Record<VariableOption, string> = {
  'Land surface temperature': 'lst-mod11a2',
  'Vegetation index (NDVI)': 'ndvi-mod13q1',
  'Enhanced vegetation (EVI)': 'evi-mod13q1',
  'Precipitation anomaly': 'precip-gpm-imerg',
}

export const THEMATIC_LAYER_METADATA: Record<
  VariableOption,
  ThematicLayerDefinition
> = {
  'Land surface temperature': {
    variable: 'Land surface temperature',
    shortTitle: 'Daytime LST',
    unit: '°C',
    layerId: 'lst-mod11a2',
    minLabel: '−20°C',
    midLabel: '+15°C',
    maxLabel: '+45°C',
    gradientCss:
      'linear-gradient(90deg, #2B5C8F 0%, #4592B0 25%, #EDE3BF 50%, #D98F73 78%, #A63A26 100%)',
    provenanceNote: 'MODIS MOD11A2.061 · Connected via GHS raster service when ingested',
    stops: [
      { value: -20, color: '#2B5C8F', rgb: [43, 92, 143] },
      { value: 0, color: '#4592B0', rgb: [69, 146, 176] },
      { value: 15, color: '#EDE3BF', rgb: [237, 227, 191] },
      { value: 30, color: '#D98F73', rgb: [217, 143, 115] },
      { value: 45, color: '#A63A26', rgb: [166, 58, 38] },
    ],
  },
  'Vegetation index (NDVI)': {
    variable: 'Vegetation index (NDVI)',
    shortTitle: 'Vegetation index',
    unit: 'NDVI',
    layerId: 'ndvi-mod13q1',
    minLabel: '−0.1',
    midLabel: '0.4',
    maxLabel: '0.9',
    gradientCss:
      'linear-gradient(90deg, #9C7860 0%, #DDD5BC 32%, #9DD2C7 68%, #2E8F81 100%)',
    provenanceNote: 'MODIS MOD13Q1.061 · Connected via GHS raster service when ingested',
    stops: [
      { value: -0.1, color: '#9C7860', rgb: [156, 120, 96] },
      { value: 0.1, color: '#DDD5BC', rgb: [221, 213, 188] },
      { value: 0.4, color: '#9DD2C7', rgb: [157, 210, 199] },
      { value: 0.9, color: '#2E8F81', rgb: [46, 143, 129] },
    ],
  },
  'Enhanced vegetation (EVI)': {
    variable: 'Enhanced vegetation (EVI)',
    shortTitle: 'Enhanced vegetation',
    unit: 'EVI',
    layerId: 'evi-mod13q1',
    minLabel: '−0.1',
    midLabel: '0.35',
    maxLabel: '0.85',
    gradientCss:
      'linear-gradient(90deg, #A48673 0%, #DFD8C4 34%, #8AC6BA 68%, #1C7C71 100%)',
    provenanceNote: 'MODIS MOD13Q1.061 · Connected via GHS raster service when ingested',
    stops: [
      { value: -0.1, color: '#A48673', rgb: [164, 134, 115] },
      { value: 0.1, color: '#DFD8C4', rgb: [223, 216, 196] },
      { value: 0.35, color: '#8AC6BA', rgb: [138, 198, 186] },
      { value: 0.85, color: '#1C7C71', rgb: [28, 124, 113] },
    ],
  },
  'Precipitation anomaly': {
    variable: 'Precipitation anomaly',
    shortTitle: 'Precipitation',
    unit: 'mm',
    layerId: 'precip-gpm-imerg',
    minLabel: '0',
    midLabel: '25',
    maxLabel: '120+',
    gradientCss:
      'linear-gradient(90deg, #F3F8F8 0%, #B8D9DE 30%, #4897B8 65%, #0B4F75 100%)',
    provenanceNote: 'GPM IMERG V07 · Connected via GHS raster service when ingested',
    stops: [
      { value: 0, color: '#F3F8F8', rgb: [243, 248, 248] },
      { value: 10, color: '#B8D9DE', rgb: [184, 217, 222] },
      { value: 25, color: '#4897B8', rgb: [72, 151, 184] },
      { value: 120, color: '#0B4F75', rgb: [11, 79, 117] },
    ],
  },
}

export function buildRegionHighlightExpression(
  selectedRegion: RegionOption,
): ExpressionSpecification {
  if (selectedRegion === 'Global land') {
    return ['literal', 'rgba(0, 0, 0, 0)'] as ExpressionSpecification
  }

  return [
    'case',
    ['==', ['get', 'terraRegion'], selectedRegion],
    'rgba(21, 155, 145, 0.08)',
    'rgba(0, 0, 0, 0)',
  ] as ExpressionSpecification
}

export function buildSelectedCountryFillExpression(
  selectedIsoA3: string | null,
): ExpressionSpecification {
  if (!selectedIsoA3) {
    return ['literal', 'rgba(0, 0, 0, 0)'] as ExpressionSpecification
  }

  return [
    'case',
    ['==', ['get', 'isoA3'], selectedIsoA3],
    'rgba(21, 155, 145, 0.14)',
    'rgba(0, 0, 0, 0)',
  ] as ExpressionSpecification
}

export function buildSelectedCountryLineExpression(
  selectedIsoA3: string | null,
): ExpressionSpecification {
  if (!selectedIsoA3) {
    return ['literal', 0] as ExpressionSpecification
  }

  return [
    'case',
    ['==', ['get', 'isoA3'], selectedIsoA3],
    1.8,
    0,
  ] as ExpressionSpecification
}

function buildWorldVectorLayers(borderVisible: boolean): LayerSpecification[] {
  const borderVisibility = borderVisible ? 'visible' : 'none'
  return [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#DCE6EC' },
    },
    {
      id: 'ofm-landcover',
      type: 'fill',
      source: 'openfreemap',
      'source-layer': 'landcover',
      paint: {
        'fill-color': [
          'match',
          ['get', 'class'],
          'wood',
          '#DFECE4',
          'forest',
          '#DFECE4',
          'grass',
          '#EAF0E6',
          'farmland',
          '#EEF1EA',
          'wetland',
          '#DCE9E8',
          'sand',
          '#F2EDE0',
          'ice',
          '#F3F7FA',
          '#F1F4F5',
        ],
        'fill-opacity': 0.85,
      },
    },
    {
      id: 'ofm-park',
      type: 'fill',
      source: 'openfreemap',
      'source-layer': 'park',
      minzoom: 5,
      paint: { 'fill-color': '#DAEBE0', 'fill-opacity': 0.55 },
    },
    {
      id: 'ofm-landuse',
      type: 'fill',
      source: 'openfreemap',
      'source-layer': 'landuse',
      minzoom: 9,
      paint: {
        'fill-color': [
          'match',
          ['get', 'class'],
          'residential',
          '#E7EBEE',
          'industrial',
          '#E1E5EA',
          'commercial',
          '#E5E9ED',
          'park',
          '#DAEBE0',
          '#EAECEF',
        ],
        'fill-opacity': 0.65,
      },
    },
    {
      id: 'ofm-water',
      type: 'fill',
      source: 'openfreemap',
      'source-layer': 'water',
      paint: { 'fill-color': '#CBE0EC' },
    },
    {
      id: 'ofm-waterway',
      type: 'line',
      source: 'openfreemap',
      'source-layer': 'waterway',
      minzoom: 3,
      paint: {
        'line-color': '#9FC7DF',
        'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.5, 8, 1.3, 14, 2.5],
      },
    },
    {
      id: 'ofm-building',
      type: 'fill',
      source: 'openfreemap',
      'source-layer': 'building',
      minzoom: 13,
      paint: {
        'fill-color': '#DCE2E8',
        'fill-outline-color': '#C6CFD8',
        'fill-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0.1, 15, 0.72],
      },
    },
    {
      id: 'ofm-road-minor',
      type: 'line',
      source: 'openfreemap',
      'source-layer': 'transportation',
      minzoom: 11,
      filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'track']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#D7DFE6',
        'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.5, 16, 2.2],
      },
    },
    {
      id: 'ofm-road-secondary',
      type: 'line',
      source: 'openfreemap',
      'source-layer': 'transportation',
      minzoom: 7,
      filter: ['in', ['get', 'class'], ['literal', ['secondary', 'tertiary']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#FFFFFF',
        'line-width': ['interpolate', ['linear'], ['zoom'], 7, 0.6, 13, 2.4, 16, 5],
      },
    },
    {
      id: 'ofm-road-primary',
      type: 'line',
      source: 'openfreemap',
      'source-layer': 'transportation',
      minzoom: 5,
      filter: ['in', ['get', 'class'], ['literal', ['primary', 'trunk']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#F2D59B',
        'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.7, 12, 2.8, 16, 6],
      },
    },
    {
      id: 'ofm-road-motorway',
      type: 'line',
      source: 'openfreemap',
      'source-layer': 'transportation',
      minzoom: 4,
      filter: ['==', ['get', 'class'], 'motorway'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#E3AD74',
        'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.8, 12, 3.2, 16, 7],
      },
    },
    {
      id: 'ofm-boundary-subnational',
      type: 'line',
      source: 'openfreemap',
      'source-layer': 'boundary',
      minzoom: 4,
      filter: ['>=', ['get', 'admin_level'], 4],
      layout: { visibility: borderVisibility },
      paint: {
        'line-color': '#B4C3CC',
        'line-width': 0.8,
        'line-dasharray': [3, 2],
      },
    },
    {
      id: 'ofm-boundary-country',
      type: 'line',
      source: 'openfreemap',
      'source-layer': 'boundary',
      filter: ['==', ['get', 'admin_level'], 2],
      layout: { visibility: borderVisibility },
      paint: {
        'line-color': '#8DA0AB',
        'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.8, 6, 1.4, 12, 2.2],
      },
    },
    {
      id: 'ofm-label-place',
      type: 'symbol',
      source: 'openfreemap',
      'source-layer': 'place',
      minzoom: 4,
      layout: {
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Regular'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 4, 10, 9, 13, 14, 15],
        'text-max-width': 8,
      },
      paint: {
        'text-color': '#2B3E4C',
        'text-halo-color': 'rgba(255, 255, 255, 0.92)',
        'text-halo-width': 1.4,
      },
    },
    {
      id: 'ofm-label-water',
      type: 'symbol',
      source: 'openfreemap',
      'source-layer': 'water_name',
      minzoom: 4,
      layout: {
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Italic'],
        'text-size': 11,
      },
      paint: {
        'text-color': '#3A6B89',
        'text-halo-color': 'rgba(255, 255, 255, 0.85)',
        'text-halo-width': 1.1,
      },
    },
    {
      id: 'ofm-label-road',
      type: 'symbol',
      source: 'openfreemap',
      'source-layer': 'transportation_name',
      minzoom: 12,
      layout: {
        'symbol-placement': 'line',
        'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
        'text-font': ['Noto Sans Regular'],
        'text-size': 10,
      },
      paint: {
        'text-color': '#495B66',
        'text-halo-color': 'rgba(255, 255, 255, 0.92)',
        'text-halo-width': 1.2,
      },
    },
  ]
}

export function buildInitialMapStyle(
  selectedRegion: RegionOption,
  selectedCountryIso: string | null,
  visibility: MapLayerVisibility,
  activeLayer: MapLayerDefinition | null,
): StyleSpecification {
  const effectiveDate = resolveLayerEffectiveDate(activeLayer, '')
  const tileUrl =
    activeLayer && activeLayer.availabilityStatus === 'connected'
      ? buildLayerTileUrlTemplate(activeLayer.id, { timestamp: effectiveDate })
      : null

  const sources: StyleSpecification['sources'] = {
    openfreemap: {
      type: 'vector',
      url: GEOSPATIAL_PUBLIC_CONFIG.openFreeMapTileJsonUrl,
    },
    'ne-countries': {
      type: 'geojson',
      data: '/data/ne_110m_countries.geojson',
      generateId: true,
    },
    graticules: {
      type: 'geojson',
      data: buildGraticuleGeoJson(),
    },
  }

  if (tileUrl) {
    sources['terra-science-raster'] = {
      type: 'raster',
      tiles: [tileUrl],
      tileSize: 256,
      maxzoom: 12,
      attribution: activeLayer?.attribution ?? 'NASA Earth Observations',
    }
  }

  const layers: LayerSpecification[] = [
    ...buildWorldVectorLayers(visibility.countryBorders),
  ]

  if (tileUrl) {
    layers.push({
      id: 'active-science-raster',
      type: 'raster',
      source: 'terra-science-raster',
      layout: {
        visibility: visibility.thematicOverlay ? 'visible' : 'none',
      },
      paint: {
        'raster-opacity': 0.82,
        'raster-resampling': 'nearest',
        'raster-fade-duration': 100,
      },
    })
  }

  layers.push(
    {
      id: 'graticule-grid-lines',
      type: 'line',
      source: 'graticules',
      filter: ['==', ['get', 'kind'], 'grid'],
      layout: {
        visibility: visibility.graticules ? 'visible' : 'none',
      },
      paint: {
        'line-color': '#5F7785',
        'line-width': 0.65,
        'line-opacity': 0.35,
        'line-dasharray': [3, 4],
      },
    },
    {
      id: 'graticule-equator-line',
      type: 'line',
      source: 'graticules',
      filter: ['==', ['get', 'kind'], 'equator'],
      layout: {
        visibility: visibility.graticules ? 'visible' : 'none',
      },
      paint: {
        'line-color': '#4F6C7A',
        'line-width': 0.85,
        'line-opacity': 0.45,
      },
    },
    {
      id: 'country-hit-fill',
      type: 'fill',
      source: 'ne-countries',
      paint: {
        'fill-color': 'rgba(0, 0, 0, 0)',
      },
    },
    {
      id: 'country-region-highlight-fill',
      type: 'fill',
      source: 'ne-countries',
      layout: {
        visibility: visibility.regionBoundaries ? 'visible' : 'none',
      },
      paint: {
        'fill-color': buildRegionHighlightExpression(selectedRegion),
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
          'rgba(21, 155, 145, 0.14)',
          'rgba(0, 0, 0, 0)',
        ],
      },
    },
    {
      id: 'country-selected-fill',
      type: 'fill',
      source: 'ne-countries',
      paint: {
        'fill-color': buildSelectedCountryFillExpression(selectedCountryIso),
      },
    },
    {
      id: 'country-borders',
      type: 'line',
      source: 'ne-countries',
      layout: {
        visibility: visibility.countryBorders ? 'visible' : 'none',
      },
      paint: {
        'line-color': '#93A7B2',
        'line-width': ['interpolate', ['linear'], ['zoom'], 0.8, 0.5, 4, 1.0],
        'line-opacity': 0.65,
      },
    },
    {
      id: 'country-selected-outline',
      type: 'line',
      source: 'ne-countries',
      paint: {
        'line-color': '#159B91',
        'line-width': buildSelectedCountryLineExpression(selectedCountryIso),
      },
    },
  )

  return {
    version: 8,
    name: 'TERRA World Observatory · OpenFreeMap',
    glyphs: GEOSPATIAL_PUBLIC_CONFIG.openFreeMapGlyphsUrl,
    sources,
    layers,
  }
}
