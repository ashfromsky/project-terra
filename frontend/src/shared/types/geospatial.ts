import type { Feature, FeatureCollection } from 'geojson'
import type {
  AvailableTimeRangeResponse,
  ColorRampStopResponse,
  LayerDefinitionResponse,
  LayerMetadataResponse,
  LayerPointInspectionResponse,
  LegendConfigurationResponse,
  MapTileSourceResponse,
  RegionGeometryOutput,
  RegionResponse,
  TemporalCoverageResponse,
} from '../api/contracts'

export type ProjectionId = 'equal-earth' | 'globe' | 'mercator'

export type BasemapId =
  | 'scientific-light'
  | 'satellite-imagery'
  | 'terrain'
  | 'viirs-true-color'

export type DataAvailabilityStatus = LayerDefinitionResponse['availabilityStatus']
export type LayerRenderingType = LayerDefinitionResponse['renderingType']
export type TileSourceFormat = LayerDefinitionResponse['supportedTileFormats'][number]
export type MapLayerGroupId = LayerDefinitionResponse['groupId']
export type ObservationGranularity = AvailableTimeRangeResponse['cadence']
export type PreviewPropertyKey = NonNullable<LayerDefinitionResponse['previewPropertyKey']>

export type ColorRampStop = ColorRampStopResponse
export type LegendConfiguration = LegendConfigurationResponse
export type TemporalCoverage = TemporalCoverageResponse
export type MapTileSource = MapTileSourceResponse
export type MapLayerMetadata = LayerMetadataResponse
export type MapLayerDefinition = LayerDefinitionResponse
export type LayerPointInspection = LayerPointInspectionResponse
export type { LayerPointInspectionResponse }

export type AoiGeometry = RegionGeometryOutput
export type AoiRole = RegionResponse['role']
export type AoiShapeType = RegionResponse['shapeType']

export interface AoiProperties {
  id: string
  name: string
  role: AoiRole
  shapeType: AoiShapeType
  sourceCrs: RegionResponse['sourceCrs']
  approxAreaKm2: number
  bbox: RegionResponse['bbox']
  centroid: RegionResponse['centroid']
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
