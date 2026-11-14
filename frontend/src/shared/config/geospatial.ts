import type {
  BasemapId,
  DataAvailabilityStatus,
  ProjectionId,
} from '../types/geospatial'

export const GEOSPATIAL_PUBLIC_CONFIG = {
  nasaGibsBaseUrl: (
    import.meta.env.VITE_NASA_GIBS_BASE_URL ?? 'https://gibs.earthdata.nasa.gov'
  ).replace(/\/+$/, ''),
  naturalEarthCountriesUrl: '/data/ne_110m_countries.geojson',
  naturalEarthCoastlineUrl: '/data/ne_110m_coastline.geojson',
} as const

export interface ProjectionDefinition {
  id: ProjectionId
  label: string
  shortLabel: string
  engine: 'd3-geo' | 'maplibre'
  epsgOrName: string
  description: string
  scientificSuitability: string
  supportsDeckGl: boolean
  supports3dGlobe: boolean
}

export const PROJECTION_REGISTRY: Record<ProjectionId, ProjectionDefinition> = {
  'equal-earth': {
    id: 'equal-earth',
    label: 'Equal Earth',
    shortLabel: 'Equal Earth',
    engine: 'd3-geo',
    epsgOrName: 'EPSG:8857 · Equal Earth',
    description:
      'Equal-area pseudocylindrical global projection rendered with d3-geo (geoEqualEarth). Preserves relative continental and biome areas.',
    scientificSuitability: 'Default global scientific representation',
    supportsDeckGl: false,
    supports3dGlobe: false,
  },
  globe: {
    id: 'globe',
    label: 'Globe 3D',
    shortLabel: 'Globe',
    engine: 'maplibre',
    epsgOrName: 'Spherical 3D Globe · MapLibre v5',
    description:
      'Interactive three-dimensional spherical Earth with atmospheric horizon and Natural Earth / NASA GIBS imagery.',
    scientificSuitability: 'Global spatial orientation without polar distortion',
    supportsDeckGl: false,
    supports3dGlobe: true,
  },
  mercator: {
    id: 'mercator',
    label: 'Mercator',
    shortLabel: 'Mercator',
    engine: 'maplibre',
    epsgOrName: 'EPSG:3857 · Web Mercator',
    description:
      'Conformal regional navigation projection with MapLibre GL JS v5 and validated deck.gl analytical overlay support.',
    scientificSuitability:
      'Visualization only: area and distance calculations belong to backend geodesic or projected services',
    supportsDeckGl: true,
    supports3dGlobe: false,
  },
}

export interface BasemapProviderConfig {
  id: BasemapId
  name: string
  shortName: string
  description: string
  availability: DataAvailabilityStatus
  providerName: string
  gibsLayerId?: string
  tileMatrixSetMercator?: string
  tileMatrixSetGeo?: string
  formatExtension?: 'jpeg' | 'png'
  minZoom: number
  maxZoom: number
  supportsTemporalTime: boolean
  defaultTime?: string
  minTime?: string
  attribution: string
  licenseNote: string
  supportsEqualEarth: boolean
  supportsGlobe: boolean
  supportsMercator: boolean
  backgroundOceanColor: string
  landFallbackColor: string
  borderColor: string
}

export const BASEMAP_PROVIDER_REGISTRY: Record<BasemapId, BasemapProviderConfig> = {
  'scientific-light': {
    id: 'scientific-light',
    name: 'Scientific Light',
    shortName: 'Light',
    description:
      'High-contrast scientific vector cartography over Natural Earth 1:110m boundaries and WGS 84 graticules.',
    availability: 'connected',
    providerName: 'Natural Earth 1:110m',
    minZoom: 0,
    maxZoom: 12,
    supportsTemporalTime: false,
    attribution: 'Natural Earth 1:110m · Public Domain',
    licenseNote: 'Public domain vector cartography',
    supportsEqualEarth: true,
    supportsGlobe: true,
    supportsMercator: true,
    backgroundOceanColor: '#f0f5f6',
    landFallbackColor: '#dfe9ec',
    borderColor: '#ffffff',
  },
  'satellite-imagery': {
    id: 'satellite-imagery',
    name: 'Satellite Imagery',
    shortName: 'Satellite',
    description:
      'Cloud-free NASA MODIS Blue Marble Next Generation global true-color satellite composite.',
    availability: 'connected',
    providerName: 'NASA EOSDIS GIBS',
    gibsLayerId: 'BlueMarble_NextGeneration',
    tileMatrixSetMercator: 'GoogleMapsCompatible_Level8',
    tileMatrixSetGeo: '500m',
    formatExtension: 'jpeg',
    minZoom: 0,
    maxZoom: 8,
    supportsTemporalTime: false,
    attribution: 'NASA EOSDIS GIBS · Blue Marble Next Generation (MODIS)',
    licenseNote: 'NASA EOSDIS open imagery',
    supportsEqualEarth: true,
    supportsGlobe: true,
    supportsMercator: true,
    backgroundOceanColor: '#0b1925',
    landFallbackColor: '#253c48',
    borderColor: 'rgba(255, 255, 255, 0.55)',
  },
  terrain: {
    id: 'terrain',
    name: 'Terrain & Bathymetry',
    shortName: 'Terrain',
    description:
      'NASA Blue Marble Shaded Relief and Ocean Bathymetry global topographic basemap.',
    availability: 'connected',
    providerName: 'NASA EOSDIS GIBS',
    gibsLayerId: 'BlueMarble_ShadedRelief_Bathymetry',
    tileMatrixSetMercator: 'GoogleMapsCompatible_Level8',
    tileMatrixSetGeo: '500m',
    formatExtension: 'jpeg',
    minZoom: 0,
    maxZoom: 8,
    supportsTemporalTime: false,
    attribution: 'NASA EOSDIS GIBS · Blue Marble Shaded Relief & Bathymetry',
    licenseNote: 'NASA EOSDIS open imagery',
    supportsEqualEarth: true,
    supportsGlobe: true,
    supportsMercator: true,
    backgroundOceanColor: '#132a3b',
    landFallbackColor: '#4c5f66',
    borderColor: 'rgba(255, 255, 255, 0.48)',
  },
  'viirs-true-color': {
    id: 'viirs-true-color',
    name: 'VIIRS Daily True Color',
    shortName: 'VIIRS Daily',
    description:
      'Daily Suomi-NPP VIIRS Corrected Reflectance satellite imagery synchronized to the selected date (2015-11-24 onward).',
    availability: 'connected',
    providerName: 'NASA EOSDIS GIBS',
    gibsLayerId: 'VIIRS_SNPP_CorrectedReflectance_TrueColor',
    tileMatrixSetMercator: 'GoogleMapsCompatible_Level9',
    tileMatrixSetGeo: '250m',
    formatExtension: 'jpeg',
    minZoom: 0,
    maxZoom: 9,
    supportsTemporalTime: true,
    defaultTime: '2026-11-02',
    minTime: '2015-11-24',
    attribution: 'NASA EOSDIS GIBS · VIIRS Suomi NPP Corrected Reflectance',
    licenseNote: 'NASA EOSDIS open imagery',
    supportsEqualEarth: false,
    supportsGlobe: true,
    supportsMercator: true,
    backgroundOceanColor: '#09141f',
    landFallbackColor: '#253c48',
    borderColor: 'rgba(255, 255, 255, 0.45)',
  },
}

export const BASEMAP_LIST: readonly BasemapProviderConfig[] = [
  BASEMAP_PROVIDER_REGISTRY['scientific-light'],
  BASEMAP_PROVIDER_REGISTRY['satellite-imagery'],
  BASEMAP_PROVIDER_REGISTRY['terrain'],
  BASEMAP_PROVIDER_REGISTRY['viirs-true-color'],
]

export function resolveGibsDate(
  selectedDate: string,
  config: BasemapProviderConfig,
): string {
  const fallback = config.defaultTime ?? '2026-11-02'
  if (!config.supportsTemporalTime) {
    return 'default'
  }
  const isoDay = selectedDate.slice(0, 10)
  if (config.minTime && isoDay < config.minTime) {
    return config.minTime
  }
  if (isoDay > fallback) {
    return fallback
  }
  return isoDay
}

export function buildGibsMercatorTileUrl(
  basemapId: BasemapId,
  selectedDate: string,
): string | null {
  const config = BASEMAP_PROVIDER_REGISTRY[basemapId]
  if (!config.gibsLayerId || !config.tileMatrixSetMercator || !config.formatExtension) {
    return null
  }
  const base = GEOSPATIAL_PUBLIC_CONFIG.nasaGibsBaseUrl
  if (config.supportsTemporalTime) {
    const time = resolveGibsDate(selectedDate, config)
    return `${base}/wmts/epsg3857/best/${config.gibsLayerId}/default/${time}/${config.tileMatrixSetMercator}/{z}/{y}/{x}.${config.formatExtension}`
  }
  return `${base}/wmts/epsg3857/best/${config.gibsLayerId}/default/${config.tileMatrixSetMercator}/{z}/{y}/{x}.${config.formatExtension}`
}

export function buildGibsEpsg4326StaticTileUrl(
  basemapId: BasemapId,
  matrix: number,
  row: number,
  col: number,
): string | null {
  const config = BASEMAP_PROVIDER_REGISTRY[basemapId]
  if (
    !config.gibsLayerId ||
    !config.tileMatrixSetGeo ||
    !config.formatExtension ||
    config.supportsTemporalTime
  ) {
    return null
  }
  const base = GEOSPATIAL_PUBLIC_CONFIG.nasaGibsBaseUrl
  return `${base}/wmts/epsg4326/best/${config.gibsLayerId}/default/${config.tileMatrixSetGeo}/${matrix}/${row}/${col}.${config.formatExtension}`
}
