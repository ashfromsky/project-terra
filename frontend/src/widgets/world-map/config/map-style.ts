import type { ExpressionSpecification, StyleSpecification } from 'maplibre-gl'
import type {
  MapLayerVisibility,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'
import type { ThematicLayerDefinition } from '../model/types'
import { buildGraticuleGeoJson } from './cartographic-data'

export const CARTOGRAPHIC_PROJECTION_SPEC = {
  datasetName: 'Natural Earth 1:110m (ne_110m_admin_0_countries, ne_110m_coastline)',
  sourceCrs: 'WGS 84 / EPSG:4326',
  renderedProjection: 'Web Mercator (EPSG:3857) flat 2D viewport',
  projectionLimitationNote:
    'In the Figma specification (nodes 5:185, 5:266, 14:6), Natural Earth refers to the 1:110m cartographic boundary dataset paired with a flat rectangular WGS 84 grid. MapLibre GL JS 5 natively supports mercator and 3D globe projections rather than a flat pseudocylindrical Natural Earth (+proj=natearth) projection, so flat 2D cartography is rendered in Web Mercator over Natural Earth 1:110m geometries.',
} as const

export const THEMATIC_LAYER_METADATA: Record<
  VariableOption,
  ThematicLayerDefinition
> = {
  'Land surface temperature': {
    variable: 'Land surface temperature',
    shortTitle: 'Temperature trend',
    unit: '°C / decade',
    propertyKey: 'demoLstTrend',
    minLabel: '−0.4',
    midLabel: '0',
    maxLabel: '+0.8',
    gradientCss:
      'linear-gradient(90deg, #3193ce 0%, #a4cfca 35%, #e8e9db 50%, #deb49f 75%, #c77f6d 100%)',
    provenanceNote: 'Synthetic demonstration field · MODIS MOD11C3 structure',
    stops: [
      { value: -0.4, color: '#3193ce', rgb: [49, 147, 206] },
      { value: 0.0, color: '#a4cfca', rgb: [164, 207, 202] },
      { value: 0.2, color: '#c6dfdf', rgb: [198, 223, 223] },
      { value: 0.32, color: '#ead6bc', rgb: [234, 214, 188] },
      { value: 0.44, color: '#e7b6a7', rgb: [231, 182, 167] },
      { value: 0.8, color: '#c77f6d', rgb: [199, 127, 109] },
    ],
  },
  'Vegetation index (NDVI)': {
    variable: 'Vegetation index (NDVI)',
    shortTitle: 'Vegetation index',
    unit: 'NDVI (0–1)',
    propertyKey: 'demoNdvi',
    minLabel: '0.0',
    midLabel: '0.5',
    maxLabel: '1.0',
    gradientCss:
      'linear-gradient(90deg, #dfb892 0%, #e7dfba 32%, #a2d4b4 68%, #159b91 100%)',
    provenanceNote: 'Synthetic demonstration field · MODIS MOD13C2 structure',
    stops: [
      { value: 0.0, color: '#dfb892', rgb: [223, 184, 146] },
      { value: 0.25, color: '#e7dfba', rgb: [231, 223, 186] },
      { value: 0.55, color: '#a2d4b4', rgb: [162, 212, 180] },
      { value: 0.85, color: '#159b91', rgb: [21, 155, 145] },
    ],
  },
  'Enhanced vegetation (EVI)': {
    variable: 'Enhanced vegetation (EVI)',
    shortTitle: 'Canopy structure',
    unit: 'EVI (0–0.8)',
    propertyKey: 'demoEvi',
    minLabel: '0.0',
    midLabel: '0.4',
    maxLabel: '0.8',
    gradientCss:
      'linear-gradient(90deg, #e5cbb0 0%, #dce4c2 35%, #8ec7be 70%, #0e7c74 100%)',
    provenanceNote: 'Synthetic demonstration field · MODIS MOD13C2 EVI structure',
    stops: [
      { value: 0.0, color: '#e5cbb0', rgb: [229, 203, 176] },
      { value: 0.22, color: '#dce4c2', rgb: [220, 228, 194] },
      { value: 0.45, color: '#8ec7be', rgb: [142, 199, 190] },
      { value: 0.7, color: '#0e7c74', rgb: [14, 124, 116] },
    ],
  },
  'Precipitation anomaly': {
    variable: 'Precipitation anomaly',
    shortTitle: 'Moisture anomaly',
    unit: 'mm / month',
    propertyKey: 'demoPrecipAnomaly',
    minLabel: '−40',
    midLabel: '0',
    maxLabel: '+40',
    gradientCss:
      'linear-gradient(90deg, #c77f6d 0%, #ead6bc 34%, #e8eef0 50%, #91c6bc 76%, #3193ce 100%)',
    provenanceNote: 'Synthetic demonstration field · Hydroclimate anomaly',
    stops: [
      { value: -35, color: '#c77f6d', rgb: [199, 127, 109] },
      { value: -15, color: '#deb49f', rgb: [222, 180, 159] },
      { value: 0, color: '#e6ecee', rgb: [230, 236, 238] },
      { value: 15, color: '#91c6bc', rgb: [145, 198, 188] },
      { value: 35, color: '#3193ce', rgb: [49, 147, 206] },
    ],
  },
}

export function getThematicFillExpression(
  variable: VariableOption,
): ExpressionSpecification {
  if (variable === 'Land surface temperature') {
    return ['coalesce', ['get', 'demoLstColor'], '#C6DFDF'] as ExpressionSpecification
  }

  const meta = THEMATIC_LAYER_METADATA[variable]
  const expression: unknown[] = [
    'interpolate',
    ['linear'],
    ['coalesce', ['get', meta.propertyKey], 0],
  ]

  for (const stop of meta.stops) {
    expression.push(stop.value, stop.color)
  }

  return expression as ExpressionSpecification
}

export function buildRegionHighlightExpression(
  selectedRegion: RegionOption,
): ExpressionSpecification {
  if (selectedRegion === 'Global land') {
    return ['literal', 'rgba(21, 155, 145, 0)'] as ExpressionSpecification
  }
  return [
    'case',
    ['==', ['get', 'terraRegion'], selectedRegion],
    'rgba(21, 155, 145, 0.16)',
    'rgba(0, 0, 0, 0)',
  ] as ExpressionSpecification
}

export function buildSelectedCountryFillExpression(
  selectedCountryIso: string | null,
): ExpressionSpecification {
  if (!selectedCountryIso) {
    return ['literal', 'rgba(21, 155, 145, 0)'] as ExpressionSpecification
  }
  return [
    'case',
    ['==', ['get', 'isoA3'], selectedCountryIso],
    'rgba(21, 155, 145, 0.28)',
    'rgba(0, 0, 0, 0)',
  ] as ExpressionSpecification
}

export function buildSelectedCountryLineExpression(
  selectedCountryIso: string | null,
): ExpressionSpecification {
  if (!selectedCountryIso) {
    return ['literal', 0] as ExpressionSpecification
  }
  return [
    'case',
    ['==', ['get', 'isoA3'], selectedCountryIso],
    2.1,
    0,
  ] as ExpressionSpecification
}

export function buildInitialMapStyle(
  variable: VariableOption,
  selectedRegion: RegionOption,
  selectedCountryIso: string | null,
  visibility: MapLayerVisibility,
): StyleSpecification {
  const graticuleGeoJson = buildGraticuleGeoJson()

  return {
    version: 8,
    name: 'TERRA Natural Earth Observatory Style',
    sources: {
      'ne-graticules': {
        type: 'geojson',
        data: graticuleGeoJson,
      },
      'ne-countries': {
        type: 'geojson',
        data: '/data/ne_110m_countries.geojson',
      },
      'ne-coastline': {
        type: 'geojson',
        data: '/data/ne_110m_coastline.geojson',
      },
    },
    layers: [
      {
        id: 'ocean-background',
        type: 'background',
        paint: {
          'background-color': '#f0f5f6',
        },
      },
      {
        id: 'graticule-grid-lines',
        type: 'line',
        source: 'ne-graticules',
        filter: ['==', ['get', 'isEquator'], false],
        layout: {
          visibility: visibility.graticules ? 'visible' : 'none',
        },
        paint: {
          'line-color': '#dbe6e9',
          'line-width': 0.85,
          'line-opacity': 0.88,
        },
      },
      {
        id: 'graticule-equator-line',
        type: 'line',
        source: 'ne-graticules',
        filter: ['==', ['get', 'isEquator'], true],
        layout: {
          visibility: visibility.graticules ? 'visible' : 'none',
        },
        paint: {
          'line-color': '#bfd2d7',
          'line-width': 1.15,
          'line-dasharray': [4, 3],
          'line-opacity': 0.95,
        },
      },
      {
        id: 'country-base-fill',
        type: 'fill',
        source: 'ne-countries',
        paint: {
          'fill-color': '#dfe9ec',
          'fill-opacity': 1,
        },
      },
      {
        id: 'country-thematic-fill',
        type: 'fill',
        source: 'ne-countries',
        layout: {
          visibility: visibility.thematicOverlay ? 'visible' : 'none',
        },
        paint: {
          'fill-color': getThematicFillExpression(variable),
          'fill-opacity': 0.92,
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
          'fill-opacity': 1,
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
          'fill-opacity': 1,
        },
      },
      {
        id: 'country-selected-fill',
        type: 'fill',
        source: 'ne-countries',
        paint: {
          'fill-color': buildSelectedCountryFillExpression(selectedCountryIso),
          'fill-opacity': 1,
        },
      },
      {
        id: 'coastline-stroke',
        type: 'line',
        source: 'ne-coastline',
        layout: {
          visibility: visibility.countryBorders ? 'visible' : 'none',
        },
        paint: {
          'line-color': '#ffffff',
          'line-width': 0.95,
          'line-opacity': 0.95,
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
          'line-color': '#ffffff',
          'line-width': 0.9,
          'line-opacity': 0.95,
        },
      },
      {
        id: 'country-hover-outline',
        type: 'line',
        source: 'ne-countries',
        paint: {
          'line-color': '#159b91',
          'line-width': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            1.6,
            0,
          ],
          'line-opacity': 1,
        },
      },
      {
        id: 'country-selected-outline',
        type: 'line',
        source: 'ne-countries',
        paint: {
          'line-color': '#0e4d4a',
          'line-width': buildSelectedCountryLineExpression(selectedCountryIso),
          'line-opacity': 1,
        },
      },
    ],
  }
}
