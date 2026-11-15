import type { ColorRampStop, MapLayerDefinition } from '../types/geospatial'

export type LiveDomain = 'vegetation' | 'temperature' | 'water' | 'soil' | 'cryosphere'
export type LiveTemporalCadence = 'daily' | '8-day' | '16-day' | 'monthly'

export interface LiveLegendStop {
  value: number
  color: string
  label: string
}

export interface LiveEnvironmentLayer {
  id: string
  name: string
  shortName: string
  domain: LiveDomain
  provider: string
  productId: string
  productVersion: string
  variable: string
  unit: string
  nativeResolution: string
  temporalCadence: LiveTemporalCadence
  description: string
  attribution: string
  tileMatrixSet: string
  defaultObservationDate: string
  valueRange: { min: number; max: number }
  legendStops: LiveLegendStop[]
  /** GIBS tiles are pre-rendered visualizations and are never numerical input. */
  calculationAvailable: false
  calculationNote: string
}

const GIBS_BASE_URL =
  import.meta.env.VITE_NASA_GIBS_BASE_URL ?? 'https://gibs.earthdata.nasa.gov'

export const LIVE_GIBS_LAYERS: readonly LiveEnvironmentLayer[] = [
  {
    id: 'MODIS_Terra_L3_NDVI_16Day',
    name: 'NDVI · MODIS Terra 16-day',
    shortName: 'NDVI 16-day',
    domain: 'vegetation',
    provider: 'NASA GIBS · LP DAAC',
    productId: 'MOD13Q1.061',
    productVersion: '061',
    variable: 'NDVI',
    unit: 'NDVI',
    nativeResolution: '250 m',
    temporalCadence: '16-day',
    description:
      'Normalized Difference Vegetation Index 16-day composite from MODIS Terra, rendered by NASA GIBS.',
    attribution: 'NASA EOSDIS GIBS · MOD13Q1.061 (visualization only)',
    tileMatrixSet: 'GoogleMapsCompatible_Level9',
    defaultObservationDate: '2026-10-16',
    valueRange: { min: -0.2, max: 1 },
    legendStops: [
      { value: -0.2, color: '#8c510a', label: '−0.2' },
      { value: 0, color: '#d8b365', label: '0' },
      { value: 0.35, color: '#f6e8c3', label: '0.35' },
      { value: 0.6, color: '#5ab4ac', label: '0.6' },
      { value: 1, color: '#01665e', label: '1' },
    ],
    calculationAvailable: false,
    calculationNote:
      'GIBS tiles are visualization only. Numerical NDVI uses MOD13Q1 COG windows from Microsoft Planetary Computer.',
  },
  {
    id: 'MODIS_Terra_L3_EVI_16Day',
    name: 'EVI · MODIS Terra 16-day',
    shortName: 'EVI 16-day',
    domain: 'vegetation',
    provider: 'NASA GIBS · LP DAAC',
    productId: 'MOD13Q1.061',
    productVersion: '061',
    variable: 'EVI',
    unit: 'EVI',
    nativeResolution: '250 m',
    temporalCadence: '16-day',
    description:
      'Enhanced Vegetation Index 16-day composite from MODIS Terra, rendered by NASA GIBS.',
    attribution: 'NASA EOSDIS GIBS · MOD13Q1.061 (visualization only)',
    tileMatrixSet: 'GoogleMapsCompatible_Level9',
    defaultObservationDate: '2026-10-16',
    valueRange: { min: -1, max: 1 },
    legendStops: [
      { value: -1, color: '#8c510a', label: '−1' },
      { value: 0, color: '#d8b365', label: '0' },
      { value: 0.5, color: '#5ab4ac', label: '0.5' },
      { value: 1, color: '#01665e', label: '1' },
    ],
    calculationAvailable: false,
    calculationNote:
      'GIBS tiles are visualization only. Numerical EVI uses MOD13Q1 COG windows from Microsoft Planetary Computer.',
  },
  {
    id: 'MODIS_Terra_Land_Surface_Temp_Day',
    name: 'Land Surface Temperature · Day',
    shortName: 'LST Day',
    domain: 'temperature',
    provider: 'NASA GIBS · LP DAAC',
    productId: 'MOD11A1.061',
    productVersion: '061',
    variable: 'LST_Day',
    unit: '°C',
    nativeResolution: '1 km',
    temporalCadence: 'daily',
    description: 'Daytime land surface temperature from MODIS Terra, rendered by NASA GIBS.',
    attribution: 'NASA EOSDIS GIBS · MOD11A1.061 (visualization only)',
    tileMatrixSet: 'GoogleMapsCompatible_Level7',
    defaultObservationDate: '2026-11-14',
    valueRange: { min: -10, max: 45 },
    legendStops: [
      { value: -10, color: '#313695', label: '−10' },
      { value: 0, color: '#74add1', label: '0' },
      { value: 20, color: '#fee090', label: '20' },
      { value: 35, color: '#f46d43', label: '35' },
      { value: 45, color: '#a50026', label: '45' },
    ],
    calculationAvailable: false,
    calculationNote: 'GIBS LST is a pre-rendered visualization; numerical LST is not yet wired.',
  },
  {
    id: 'MODIS_Terra_Land_Surface_Temp_Night',
    name: 'Land Surface Temperature · Night',
    shortName: 'LST Night',
    domain: 'temperature',
    provider: 'NASA GIBS · LP DAAC',
    productId: 'MOD11A1.061',
    productVersion: '061',
    variable: 'LST_Night',
    unit: '°C',
    nativeResolution: '1 km',
    temporalCadence: 'daily',
    description: 'Night-time land surface temperature from MODIS Terra, rendered by NASA GIBS.',
    attribution: 'NASA EOSDIS GIBS · MOD11A1.061 (visualization only)',
    tileMatrixSet: 'GoogleMapsCompatible_Level7',
    defaultObservationDate: '2026-11-14',
    valueRange: { min: -20, max: 35 },
    legendStops: [
      { value: -20, color: '#313695', label: '−20' },
      { value: -5, color: '#74add1', label: '−5' },
      { value: 10, color: '#fee090', label: '10' },
      { value: 25, color: '#f46d43', label: '25' },
      { value: 35, color: '#a50026', label: '35' },
    ],
    calculationAvailable: false,
    calculationNote: 'GIBS LST is a pre-rendered visualization; numerical LST is not yet wired.',
  },
  {
    id: 'IMERG_Precipitation_Rate',
    name: 'Precipitation Rate · GPM IMERG',
    shortName: 'IMERG Precipitation',
    domain: 'water',
    provider: 'NASA GIBS · GES DISC',
    productId: 'GPM_3IMERGHH.07',
    productVersion: '07',
    variable: 'precipitation',
    unit: 'mm/hr',
    nativeResolution: '0.1° (~10 km)',
    temporalCadence: 'daily',
    description: 'Global precipitation rate from GPM IMERG, rendered by NASA GIBS.',
    attribution: 'NASA EOSDIS GIBS · GPM IMERG V07 (visualization only)',
    tileMatrixSet: 'GoogleMapsCompatible_Level6',
    defaultObservationDate: '2026-11-14',
    valueRange: { min: 0, max: 30 },
    legendStops: [
      { value: 0, color: '#eff3ff', label: '0' },
      { value: 2, color: '#9ecae1', label: '2' },
      { value: 5, color: '#3182bd', label: '5' },
      { value: 12, color: '#08519c', label: '12' },
      { value: 30, color: '#54278f', label: '30' },
    ],
    calculationAvailable: false,
    calculationNote:
      'GIBS IMERG tiles are visualization only. Point precipitation calculations use NASA POWER.',
  },
  {
    id: 'SMAP_L4_Analyzed_Surface_Soil_Moisture',
    name: 'Surface Soil Moisture · SMAP',
    shortName: 'SMAP Soil Moisture',
    domain: 'soil',
    provider: 'NASA GIBS · NSIDC',
    productId: 'SPL4SMAU.001',
    productVersion: '001',
    variable: 'soil_moisture',
    unit: 'm³/m³',
    nativeResolution: '9 km',
    temporalCadence: 'daily',
    description: 'SMAP Level-4 surface soil moisture, rendered by NASA GIBS.',
    attribution: 'NASA EOSDIS GIBS · SMAP L4 (visualization only)',
    tileMatrixSet: 'GoogleMapsCompatible_Level6',
    defaultObservationDate: '2026-11-10',
    valueRange: { min: 0, max: 0.6 },
    legendStops: [
      { value: 0, color: '#f7f4e9', label: '0' },
      { value: 0.1, color: '#c7e9c0', label: '0.1' },
      { value: 0.25, color: '#74c476', label: '0.25' },
      { value: 0.4, color: '#238b45', label: '0.4' },
      { value: 0.6, color: '#00441b', label: '0.6' },
    ],
    calculationAvailable: false,
    calculationNote: 'GIBS SMAP tiles are visualization only; numerical SMAP extraction is not wired.',
  },
  {
    id: 'MODIS_Terra_NDSI_Snow_Cover',
    name: 'Snow Cover · MODIS NDSI',
    shortName: 'Snow Cover',
    domain: 'cryosphere',
    provider: 'NASA GIBS · NSIDC',
    productId: 'MOD10A1.061',
    productVersion: '061',
    variable: 'NDSI_Snow_Cover',
    unit: 'index',
    nativeResolution: '500 m',
    temporalCadence: 'daily',
    description: 'Normalized Difference Snow Index snow cover from MODIS Terra, rendered by GIBS.',
    attribution: 'NASA EOSDIS GIBS · MOD10A1.061 (visualization only)',
    tileMatrixSet: 'GoogleMapsCompatible_Level8',
    defaultObservationDate: '2026-11-14',
    valueRange: { min: 0, max: 100 },
    legendStops: [
      { value: 0, color: '#ffffff', label: '0' },
      { value: 20, color: '#d9f0ff', label: '20' },
      { value: 50, color: '#74a9cf', label: '50' },
      { value: 80, color: '#0570b0', label: '80' },
      { value: 100, color: '#023858', label: '100' },
    ],
    calculationAvailable: false,
    calculationNote: 'GIBS snow-cover tiles are visualization only.',
  },
]

export function findLiveLayer(id: string | null): LiveEnvironmentLayer | null {
  if (!id) return null
  return LIVE_GIBS_LAYERS.find((layer) => layer.id === id) ?? null
}

export function buildGibsLiveTileUrl(layer: LiveEnvironmentLayer, date: string): string {
  const day = /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : layer.defaultObservationDate
  return `${GIBS_BASE_URL}/wmts/epsg3857/best/${layer.id}/default/${day}/${layer.tileMatrixSet}/{z}/{y}/{x}.png`
}

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '')
  return [
    Number.parseInt(value.slice(0, 2), 16),
    Number.parseInt(value.slice(2, 4), 16),
    Number.parseInt(value.slice(4, 6), 16),
  ]
}

function cadenceToAvailableRange(cadence: LiveTemporalCadence): 'daily' | '8-day' | '16-day' {
  if (cadence === '8-day') return '8-day'
  if (cadence === '16-day') return '16-day'
  return 'daily'
}

export function buildGibsMapLayer(
  liveLayer: LiveEnvironmentLayer,
  date: string,
): MapLayerDefinition {
  const stops: ColorRampStop[] = liveLayer.legendStops.map((stop) => ({
    value: stop.value,
    color: stop.color,
    rgb: hexToRgb(stop.color),
    label: stop.label,
  }))
  const mid = liveLayer.legendStops[Math.floor(liveLayer.legendStops.length / 2)]
  const gradient = `linear-gradient(to right, ${liveLayer.legendStops
    .map((stop) => stop.color)
    .join(', ')})`
  return {
    id: liveLayer.id,
    name: liveLayer.name,
    shortName: liveLayer.shortName,
    groupId:
      liveLayer.domain === 'vegetation'
        ? 'vegetation'
        : liveLayer.domain === 'temperature'
          ? 'temperature'
          : 'water',
    description: liveLayer.description,
    dataSource: liveLayer.provider,
    productId: liveLayer.productId,
    productVersion: liveLayer.productVersion,
    variable: liveLayer.variable,
    unit: liveLayer.unit,
    nativeSpatialResolution: liveLayer.nativeResolution,
    temporalResolution: liveLayer.temporalCadence,
    availableTimeRange: {
      start: '2000-01-01',
      end: date,
      cadence: cadenceToAvailableRange(liveLayer.temporalCadence),
    },
    attribution: liveLayer.attribution,
    availabilityStatus: 'connected',
    renderingType: 'raster',
    supportedTileFormats: ['wmts', 'xyz'],
    qaPolicy: 'NASA GIBS pre-rendered visualization; not quantitative input',
    limitations:
      'Rendered by NASA GIBS for visualization. Never use tile colours as numerical NDVI, LST, precipitation or soil-moisture values.',
    isExperimental: false,
    isSyntheticPreview: false,
    availableDates: [date],
    datasetBbox: null,
    activeDatasetId: null,
    unavailableReason: null,
    colorRamp: stops,
    valueRange: {
      min: liveLayer.valueRange.min,
      max: liveLayer.valueRange.max,
      defaultMin: liveLayer.valueRange.min,
      defaultMax: liveLayer.valueRange.max,
      step: 0.01,
    },
    legend: {
      title: liveLayer.name,
      unit: liveLayer.unit,
      minLabel: String(liveLayer.valueRange.min),
      midLabel: mid?.label ?? '',
      maxLabel: String(liveLayer.valueRange.max),
      gradientCss: gradient,
      nodataColor: '#808080',
      nodataLabel: 'No data',
      stops,
    },
    tileSource: {
      id: 'nasa-gibs-live',
      format: 'xyz',
      urlTemplate: buildGibsLiveTileUrl(liveLayer, date),
      crs: 'EPSG:3857',
      requiresBackendAuthorization: false,
      isConnected: true,
    },
  }
}

export const POWER_PARAMETERS = {
  T2M: { label: 'Temperature', unit: '°C' },
  T2M_MAX: { label: 'Max temperature', unit: '°C' },
  T2M_MIN: { label: 'Min temperature', unit: '°C' },
  RH2M: { label: 'Relative humidity', unit: '%' },
  PRECTOTCORR: { label: 'Precipitation', unit: 'mm/day' },
  ALLSKY_SFC_SW_DWN: { label: 'Solar radiation', unit: 'MJ/m²/day' },
  WS10M: { label: 'Wind speed', unit: 'm/s' },
} as const

export type PowerParameter = keyof typeof POWER_PARAMETERS

export const POWER_MONTHLY_ENDPOINT =
  'https://power.larc.nasa.gov/api/temporal/monthly/point'

export const MODIS_STAC_SEARCH_ENDPOINT =
  'https://planetarycomputer.microsoft.com/api/stac/v1/search'

export const PLANETARY_COMPUTER_SIGN_ENDPOINT =
  'https://planetarycomputer.microsoft.com/api/sas/v1/sign'

export const PLANETARY_COMPUTER_TOKEN_ENDPOINT =
  'https://planetarycomputer.microsoft.com/api/sas/v1/token'

export const MODIS_NDVI_COLLECTION = 'modis-13Q1-061'
export const MODIS_NDVI_ASSET = '250m_16_days_NDVI'
export const MODIS_EVI_ASSET = '250m_16_days_EVI'
