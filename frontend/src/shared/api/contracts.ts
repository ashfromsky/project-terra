import type { components, operations, paths } from './generated/schema'

export type { components, operations, paths }

export type HealthResponse = components['schemas']['HealthResponse']
export type DependencyHealth = components['schemas']['DependencyHealth']
export type ReadinessResponse = components['schemas']['ReadinessResponse']
export type SystemInfoResponse = components['schemas']['SystemInfoResponse']

export type UserResponse = components['schemas']['UserResponse']
export type GitHubLoginResponse = components['schemas']['GitHubLoginResponse']
export type AuthCallbackResponse = components['schemas']['AuthCallbackResponse']
export type LogoutResponse = components['schemas']['LogoutResponse']

export type ColorRampStopResponse = components['schemas']['ColorRampStopResponse']
export type ValueRangeResponse = components['schemas']['ValueRangeResponse']
export type AvailableTimeRangeResponse = components['schemas']['AvailableTimeRangeResponse']
export type LegendConfigurationResponse = components['schemas']['LegendConfigurationResponse']
export type MapTileSourceResponse = components['schemas']['MapTileSourceResponse']
export type LayerMetadataResponse = components['schemas']['LayerMetadataResponse']
export type LayerDefinitionResponse = components['schemas']['LayerDefinitionResponse']
export type LayerLegendResponse = components['schemas']['LayerLegendResponse']
export type TemporalCoverageResponse = components['schemas']['TemporalCoverageResponse']

export type GeoJsonPolygonSchema = components['schemas']['GeoJsonPolygonSchema']
export type GeoJsonMultiPolygonSchema = components['schemas']['GeoJsonMultiPolygonSchema']
export type GeoJsonPolygonInputSchema = components['schemas']['GeoJsonPolygonInputSchema']
export type GeoJsonMultiPolygonInputSchema = components['schemas']['GeoJsonMultiPolygonInputSchema']
export type RegionCreateRequest = components['schemas']['RegionCreateRequest']
export type RegionUpdateMetadataRequest = components['schemas']['RegionUpdateMetadataRequest']
export type RegionUpdateGeometryRequest = components['schemas']['RegionUpdateGeometryRequest']
export type RegionResponse = components['schemas']['RegionResponse']
export type AoiPropertiesResponse = components['schemas']['AoiPropertiesResponse']
export type RegionGeometryResponse = components['schemas']['RegionGeometryResponse']
export type RegionStatisticsResponse = components['schemas']['RegionStatisticsResponse']
export type RegionGeometryInput = RegionCreateRequest['geometry']
export type RegionGeometryOutput = RegionResponse['geometry']
