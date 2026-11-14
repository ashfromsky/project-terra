import { describe, expect, it } from 'vitest'
import { ApiError, extractErrorDetail, unwrapApiResponse } from '../client'
import { buildGitHubLoginUrl } from '../auth'
import type { RegionResponse } from '../contracts'
import { regionResponseToAoiFeature, toRegionGeometryInput } from '../regions'
import { normalizeAoiGeometry } from '../../lib/geojson-utils'
import type { AoiGeometry, MapLayerDefinition } from '../../types/geospatial'
import { resolveLayerControlState } from '../../../features/map-explorer/model/explore-store.types'

function makeSampleLayer(overrides?: Partial<MapLayerDefinition>): MapLayerDefinition {
  return {
    id: 'ndvi-mod13q1',
    name: 'MODIS NDVI',
    shortName: 'NDVI',
    groupId: 'vegetation',
    description: '16-day vegetation greenness',
    dataSource: 'NASA LP DAAC',
    productId: 'MOD13Q1',
    productVersion: '061',
    variable: 'NDVI',
    unit: 'index',
    nativeSpatialResolution: '250 m',
    temporalResolution: '16-day',
    availableTimeRange: {
      start: '2020-01-01',
      end: '2025-12-31',
      cadence: '16-day',
    },
    attribution: 'NASA EOSDIS',
    availabilityStatus: 'connected',
    renderingType: 'raster',
    supportedTileFormats: ['wmts'],
    qaPolicy: 'MODIS pixel reliability QA',
    limitations: 'Cloud contamination reduces clear-sky composite count.',
    isExperimental: false,
    isSyntheticPreview: false,
    previewPropertyKey: 'demoNdvi',
    colorRamp: [
      { value: 0, color: '#f7fcf5', rgb: [247, 252, 245], label: '0.0' },
      { value: 1, color: '#00441b', rgb: [0, 68, 27], label: '1.0' },
    ],
    valueRange: {
      min: -0.2,
      max: 1.0,
      defaultMin: 0.0,
      defaultMax: 0.9,
      step: 0.05,
    },
    legend: {
      title: 'NDVI',
      unit: 'index',
      minLabel: '0.0',
      midLabel: '0.45',
      maxLabel: '0.9',
      gradientCss: 'linear-gradient(to right, #f7fcf5, #00441b)',
      nodataColor: '#d0d7de',
      nodataLabel: 'No data',
      stops: [
        { value: 0, color: '#f7fcf5', rgb: [247, 252, 245], label: '0.0' },
        { value: 1, color: '#00441b', rgb: [0, 68, 27], label: '1.0' },
      ],
    },
    tileSource: {
      id: 'modis-ndvi',
      format: 'wmts',
      urlTemplate: null,
      crs: 'EPSG:3857',
      requiresBackendAuthorization: false,
      isConnected: true,
    },
    ...overrides,
  }
}

function makeSampleRegion(overrides?: Partial<RegionResponse>): RegionResponse {
  return {
    id: '550e8400-e29b-41d4-a716-446655440000',
    name: 'Caatinga North',
    description: 'Semi-arid benchmark polygon',
    role: 'regionA',
    shapeType: 'polygon',
    isoA3: null,
    sourceCrs: 'EPSG:4326',
    approxAreaKm2: 12450.5,
    bbox: [-41.0, -9.5, -39.5, -8.0],
    centroid: [-40.25, -8.75],
    vertexCount: 5,
    polygonCount: 1,
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [-41.0, -9.5],
          [-39.5, -9.5],
          [-39.5, -8.0],
          [-41.0, -8.0],
          [-41.0, -9.5],
        ],
      ],
    },
    createdAt: '2026-11-14T12:00:00Z',
    updatedAt: '2026-11-14T12:00:00Z',
    ...overrides,
  }
}

describe('extractErrorDetail', () => {
  it('extracts string detail and FastAPI validation error lists', () => {
    expect(extractErrorDetail({ detail: 'Invalid region geometry' })).toBe('Invalid region geometry')
    expect(
      extractErrorDetail({
        detail: [{ msg: 'Field required' }, { msg: 'Coordinate out of WGS 84 bounds' }],
      }),
    ).toBe('Field required; Coordinate out of WGS 84 bounds')
  })

  it('returns null when detail is missing or empty', () => {
    expect(extractErrorDetail(null)).toBeNull()
    expect(extractErrorDetail({ detail: '   ' })).toBeNull()
    expect(extractErrorDetail({ detail: [] })).toBeNull()
    expect(extractErrorDetail({ detail: [{ code: 'invalid' }] })).toBeNull()
  })
})

describe('unwrapApiResponse', () => {
  it('returns typed data with tuple contracts when response is ok', () => {
    const region = makeSampleRegion()
    const unwrapped = unwrapApiResponse<RegionResponse>(
      {
        data: region,
        response: new Response(null, { status: 200 }),
      },
      'GET /api/v1/regions/1',
    )
    expect(unwrapped.bbox).toEqual([-41.0, -9.5, -39.5, -8.0])
    expect(unwrapped.centroid).toEqual([-40.25, -8.75])
  })

  it('throws ApiError with status and detail on error responses', () => {
    let caught: unknown
    try {
      unwrapApiResponse<RegionResponse>(
        {
          error: { detail: 'Authentication required' },
          response: new Response(null, { status: 401 }),
        },
        'GET /api/v1/regions',
      )
    } catch (error) {
      caught = error
    }

    expect(caught).toBeInstanceOf(ApiError)
    expect(caught).toMatchObject({
      status: 401,
      message: 'Authentication required',
      detail: 'Authentication required',
    })
  })

  it('uses fallback context when error payload contains no detail', () => {
    expect(() =>
      unwrapApiResponse<RegionResponse>(
        {
          data: undefined,
          error: undefined,
          response: new Response(null, { status: 503 }),
        },
        'GET /api/v1/layers',
      ),
    ).toThrow('GET /api/v1/layers failed with status 503')
  })
})

describe('buildGitHubLoginUrl', () => {
  it('appends safe relative returnTo paths and rejects external or protocol-relative targets', () => {
    expect(buildGitHubLoginUrl('/explore?layer=ndvi-mod13q1')).toBe(
      '/api/v1/auth/github/login?redirect=true&returnTo=%2Fexplore%3Flayer%3Dndvi-mod13q1',
    )
    expect(buildGitHubLoginUrl('//evil.example/steal')).toBe('/api/v1/auth/github/login?redirect=true')
    expect(buildGitHubLoginUrl('https://evil.example/steal')).toBe('/api/v1/auth/github/login?redirect=true')
    expect(buildGitHubLoginUrl('explore')).toBe('/api/v1/auth/github/login?redirect=true')
    expect(buildGitHubLoginUrl()).toBe('/api/v1/auth/github/login?redirect=true')
  })
})

describe('region adapters and GeoJSON normalization', () => {
  it('converts RegionResponse to AoiFeature while mapping nullable isoA3 to undefined', () => {
    const region = makeSampleRegion({ isoA3: 'BRA' })
    const feature = regionResponseToAoiFeature(region)

    expect(feature.type).toBe('Feature')
    expect(feature.id).toBe(region.id)
    expect(feature.properties).toEqual({
      id: region.id,
      name: 'Caatinga North',
      role: 'regionA',
      shapeType: 'polygon',
      sourceCrs: 'EPSG:4326',
      approxAreaKm2: 12450.5,
      bbox: [-41.0, -9.5, -39.5, -8.0],
      centroid: [-40.25, -8.75],
      createdAt: '2026-11-14T12:00:00Z',
      isoA3: 'BRA',
    })
    expect(regionResponseToAoiFeature(makeSampleRegion({ isoA3: null })).properties.isoA3).toBeUndefined()
  })

  it('converts Polygon and MultiPolygon AOI geometries to strict [lon, lat] input payloads', () => {
    const polygon: AoiGeometry = {
      type: 'Polygon',
      coordinates: [
        [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 0],
        ],
      ],
    }
    const multiPolygon: AoiGeometry = {
      type: 'MultiPolygon',
      coordinates: [polygon.coordinates],
    }

    expect(toRegionGeometryInput(polygon)).toEqual(polygon)
    expect(toRegionGeometryInput(multiPolygon)).toEqual(multiPolygon)
  })

  it('normalizes valid GeoJSON geometries and strips invalid structures', () => {
    const withAltitude = {
      type: 'Polygon',
      coordinates: [
        [
          [-40, -9, 300],
          [-39, -9, 300],
          [-39, -8, 300],
          [-40, -9, 300],
        ],
      ],
    }
    expect(normalizeAoiGeometry(withAltitude)).toEqual({
      type: 'Polygon',
      coordinates: [
        [
          [-40, -9],
          [-39, -9],
          [-39, -8],
          [-40, -9],
        ],
      ],
    })

    expect(normalizeAoiGeometry({ type: 'Point', coordinates: [10, 20] })).toBeNull()
    expect(
      normalizeAoiGeometry({ type: 'Polygon', coordinates: [[[10, Number.NaN], [11, 2], [11, 3]]] }),
    ).toBeNull()
    expect(normalizeAoiGeometry(null)).toBeNull()
  })
})

describe('resolveLayerControlState', () => {
  it('derives defaults from API layer metadata and applies partial overrides', () => {
    const layer = makeSampleLayer()

    expect(resolveLayerControlState(layer, undefined, 'ndvi-mod13q1')).toEqual({
      visible: true,
      opacity: 0.85,
      minValue: 0.0,
      maxValue: 0.9,
    })

    expect(resolveLayerControlState(layer, undefined, 'lst-mod11a2')).toEqual({
      visible: false,
      opacity: 0.85,
      minValue: 0.0,
      maxValue: 0.9,
    })

    expect(
      resolveLayerControlState(layer, { opacity: 0.4, minValue: 0.2 }, 'lst-mod11a2'),
    ).toEqual({
      visible: false,
      opacity: 0.4,
      minValue: 0.2,
      maxValue: 0.9,
    })
  })
})
