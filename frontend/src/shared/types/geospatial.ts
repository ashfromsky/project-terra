import type { Feature, FeatureCollection, MultiPolygon, Polygon } from 'geojson'

export type ProjectionId = 'equal-earth' | 'globe' | 'mercator'

export type BasemapId =
  | 'scientific-light'
  | 'satellite-imagery'
  | 'terrain'
  | 'viirs-true-color'

export type DataAvailabilityStatus =
  | 'connected'
  | 'preview'
  | 'planned'
  | 'unavailable'

export type LayerRenderingType = 'raster' | 'choropleth' | 'vector' | 'point'

export type TileSourceFormat = 'geojson' | 'mvt' | 'tilejson' | 'cog' | 'zarr' | 'wmts'

export type MapLayerGroupId = 'vegetation' | 'temperature' | 'water' | 'derived'

export type ObservationGranularity =
  | '30-minute'
  | 'daily'
  | '8-day'
  | '16-day'
  | 'monthly'
  | 'multi-year'

export interface ColorRampStop {
  value: number
  color: string
  rgb: [number, number, number]
  label?: string
}

export interface LegendConfiguration {
  title: string
  unit: string
  minLabel: string
  midLabel: string
  maxLabel: string
  gradientCss: string
  nodataColor: string
  nodataLabel: string
  stops: readonly ColorRampStop[]
}

export interface TemporalCoverage {
  startDate: string
  endDate: string
  cadence: ObservationGranularity
  totalExpectedSteps: number
  availableSteps: number
  coveragePercent: number
  notes: string
  isSimulatedCoverage: boolean
}

export interface MapTileSource {
  id: string
  format: TileSourceFormat
  urlTemplate: string | null
  tileMatrixSet?: string
  minZoom?: number
  maxZoom?: number
  tileSize?: number
  crs: 'EPSG:4326' | 'EPSG:3857'
  requiresBackendAuthorization: boolean
  isConnected: boolean
}

export interface MapLayerMetadata {
  id: string
  name: string
  shortName: string
  groupId: MapLayerGroupId
  description: string
  dataSource: string
  productId: string
  productVersion: string
  variable: string
  unit: string
  nativeSpatialResolution: string
  temporalResolution: string
  availableTimeRange: {
    start: string
    end: string
    cadence: ObservationGranularity
  }
  attribution: string
  availabilityStatus: DataAvailabilityStatus
  renderingType: LayerRenderingType
  supportedTileFormats: readonly TileSourceFormat[]
  qaPolicy: string
  limitations: string
  isExperimental?: boolean
  isSyntheticPreview?: boolean
  previewPropertyKey?: 'demoLstTrend' | 'demoNdvi' | 'demoEvi' | 'demoPrecipAnomaly'
}

export interface MapLayerDefinition extends MapLayerMetadata {
  colorRamp: readonly ColorRampStop[]
  valueRange: {
    min: number
    max: number
    defaultMin: number
    defaultMax: number
    step: number
  }
  legend: LegendConfiguration
  tileSource: MapTileSource
}

export interface DataQualityInfo {
  status: DataAvailabilityStatus
  qaFlagSummary: string
  validPixelPercent: number | null
  cloudMasked: boolean | null
  isSyntheticDemo: boolean
  notes: string
}

export interface PointObservation {
  layerId: string
  coordinates: {
    longitude: number
    latitude: number
    crs: 'EPSG:4326'
  }
  requestedDate: string
  observationDate: string | null
  value: number | null
  formattedValue: string
  unit: string
  dataSource: string
  productId: string
  productVersion: string
  nativeSpatialResolution: string
  quality: DataQualityInfo
  availabilityStatus: DataAvailabilityStatus
  message: string
}

export interface AreaObservation {
  layerId: string
  aoiId: string
  aoiName: string
  startDate: string
  endDate: string
  meanValue: number | null
  minValue: number | null
  maxValue: number | null
  unit: string
  validCoveragePercent: number | null
  pixelCount: number | null
  nativeSpatialResolution: string
  quality: DataQualityInfo
  availabilityStatus: DataAvailabilityStatus
  message: string
}

export type AoiGeometry = Polygon | MultiPolygon

export type AoiRole = 'primary' | 'regionA' | 'regionB'

export type AoiShapeType = 'feature' | 'polygon' | 'rectangle'

export interface AoiProperties {
  id: string
  name: string
  role: AoiRole
  shapeType: AoiShapeType
  sourceCrs: 'EPSG:4326'
  approxAreaKm2: number
  bbox: [number, number, number, number]
  centroid: [number, number]
  createdAt: string
  isoA3?: string
}

export type AoiFeature = Feature<AoiGeometry, AoiProperties>

export type AoiFeatureCollection = FeatureCollection<AoiGeometry, AoiProperties>

export interface MapViewportState {
  center: [number, number]
  zoom: number
  bearing: number
  pitch: number
}

export interface InspectPointParams {
  layerId: string
  longitude: number
  latitude: number
  date: string
}

export interface InspectAreaParams {
  layerId: string
  aoi: AoiFeature
  startDate: string
  endDate: string
}

export interface MapDataProvider {
  readonly providerId: string
  readonly isConnectedBackend: boolean
  getLayers(): Promise<readonly MapLayerDefinition[]>
  getLayerMetadata(layerId: string): Promise<MapLayerDefinition | null>
  getTemporalCoverage(layerId: string): Promise<TemporalCoverage | null>
  inspectPoint(params: InspectPointParams): Promise<PointObservation>
  getAreaObservation(params: InspectAreaParams): Promise<AreaObservation>
}
