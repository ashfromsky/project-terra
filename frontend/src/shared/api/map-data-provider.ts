import {
  ENVIRONMENTAL_LAYER_CATALOG,
  getLayerDefinition,
} from '../../entities/layer/model/layer-catalog'
import type {
  AreaObservation,
  InspectAreaParams,
  InspectPointParams,
  MapDataProvider,
  MapLayerDefinition,
  PointObservation,
  TemporalCoverage,
} from '../types/geospatial'

export class MockMapDataProvider implements MapDataProvider {
  readonly providerId = 'mock-map-data-provider-v1'
  readonly isConnectedBackend = false

  async getLayers(): Promise<readonly MapLayerDefinition[]> {
    return ENVIRONMENTAL_LAYER_CATALOG
  }

  async getLayerMetadata(layerId: string): Promise<MapLayerDefinition | null> {
    return ENVIRONMENTAL_LAYER_CATALOG.find((item) => item.id === layerId) ?? null
  }

  async getTemporalCoverage(layerId: string): Promise<TemporalCoverage | null> {
    const layer = getLayerDefinition(layerId)
    const startYear = Number(layer.availableTimeRange.start.slice(0, 4))
    const endYear = Number(layer.availableTimeRange.end.slice(0, 4))
    const years = Math.max(1, endYear - startYear + 1)
    const stepsPerYear =
      layer.availableTimeRange.cadence === '16-day'
        ? 23
        : layer.availableTimeRange.cadence === '8-day'
          ? 46
          : layer.availableTimeRange.cadence === 'daily'
            ? 365
            : 12
    const totalExpectedSteps = years * stepsPerYear

    return {
      startDate: layer.availableTimeRange.start,
      endDate: layer.availableTimeRange.end,
      cadence: layer.availableTimeRange.cadence,
      totalExpectedSteps,
      availableSteps: 0,
      coveragePercent: 0,
      notes:
        'Nominal NASA product archive bounds shown for planning. Live granule discovery and valid-observation counts require backend Earthdata / Worker ingestion.',
      isSimulatedCoverage: true,
    }
  }

  async inspectPoint(params: InspectPointParams): Promise<PointObservation> {
    const layer = getLayerDefinition(params.layerId)
    return {
      layerId: layer.id,
      coordinates: {
        longitude: Number(params.longitude.toFixed(5)),
        latitude: Number(params.latitude.toFixed(5)),
        crs: 'EPSG:4326',
      },
      requestedDate: params.date,
      observationDate: null,
      value: null,
      formattedValue: 'Observation data not connected',
      unit: layer.unit,
      dataSource: layer.dataSource,
      productId: layer.productId,
      productVersion: layer.productVersion,
      nativeSpatialResolution: layer.nativeSpatialResolution,
      quality: {
        status: 'unavailable',
        qaFlagSummary: layer.qaPolicy,
        validPixelPercent: null,
        cloudMasked: null,
        isSyntheticDemo: false,
        notes:
          'Coordinate click records WGS 84 (EPSG:4326) position only. Pixel-level values are not interpolated in the browser and await backend COG / Zarr sampling.',
      },
      availabilityStatus: 'unavailable',
      message:
        `Actual ${layer.productId}.${layer.productVersion} pixel observations at native ${layer.nativeSpatialResolution} resolution are not connected yet.`,
    }
  }

  async getAreaObservation(params: InspectAreaParams): Promise<AreaObservation> {
    const layer = getLayerDefinition(params.layerId)
    return {
      layerId: layer.id,
      aoiId: params.aoi.properties.id,
      aoiName: params.aoi.properties.name,
      startDate: params.startDate,
      endDate: params.endDate,
      meanValue: null,
      minValue: null,
      maxValue: null,
      unit: layer.unit,
      validCoveragePercent: null,
      pixelCount: null,
      nativeSpatialResolution: layer.nativeSpatialResolution,
      quality: {
        status: 'unavailable',
        qaFlagSummary: layer.qaPolicy,
        validPixelPercent: null,
        cloudMasked: null,
        isSyntheticDemo: false,
        notes:
          'Zonal statistics and difference maps require backend geospatial processing over native product grids.',
      },
      availabilityStatus: 'unavailable',
      message:
        `Regional zonal statistics for "${params.aoi.properties.name}" are not connected. No scientific values were computed in the browser.`,
    }
  }
}

export const defaultMapDataProvider: MapDataProvider = new MockMapDataProvider()
