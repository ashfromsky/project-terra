import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetchClient, extractErrorDetail, unwrapApiResponse } from '../client'
import { buildGitHubLoginUrl, loginDevSession } from '../auth'
import {
  compareAssessments,
  createAssessment,
  executeAssessment,
  fetchAssessmentDetail,
  fetchAssessmentMethods,
  fetchAssessments,
  parseScientificAssessmentResult,
} from '../assessments'
import {
  discoverObservations,
  fetchPreparedDatasets,
  fetchProviders,
  startIngestion,
} from '../data-sources'
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
      maxValue: 0.9,
      minValue: 0.2,
    })
  })
})

describe('assessments API adapters and result parser', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('parses separated resilience dimensions, event traceability, quality, uncertainty, and provenance', () => {
    const parsed = parseScientificAssessmentResult({
      assessment_id: 'assess-001',
      status: 'completed_partial',
      warnings: ['Censored post-event window.'],
      errors: [],
      stages: [
        {
          stage_name: 'disturbance_recovery_resilience',
          priority: 'P1',
          status: 'completed',
          duration_ms: 12.4,
          warnings: [],
          errors: [],
        },
      ],
      quality_reports: [
        {
          dataset_id: 'mod13-poly',
          variable_name: 'NDVI',
          total_steps: 84,
          valid_steps: 80,
          missing_steps: 4,
          valid_fraction: 0.9524,
          missing_fraction: 0.0476,
          qa_screened_out_count: 3,
          out_of_range_count: 1,
          warnings: [],
        },
      ],
      trends: [
        {
          dataset_id: 'mod13-poly',
          variable_name: 'NDVI',
          variant: 'deseasonalized',
          sample_count: 84,
          valid_count: 80,
          direction: 'no_trend',
          p_value: 0.42,
          sens_slope: 0.0012,
          slope_unit: 'dimensionless/year',
          warnings: [],
        },
      ],
      resilience: [
        {
          dataset_id: 'mod13-poly',
          variable_name: 'NDVI',
          resistance: {
            dimension: 'resistance',
            available: true,
            status: 'completed',
            value: 0.25,
            unit: 'dimensionless_(0..1]',
            formula: 'mean_i(1 / (1 + |z_neg_peak,i|))',
            interpretation: 'Negative peak deflection.',
            assumptions: [],
            limitations: [],
            event_values: [
              {
                event_start: '2022-06-01T00:00:00Z',
                event_end: '2022-08-01T00:00:00Z',
                peak_negative_zscore: -3.0,
                resistance: 0.25,
              },
            ],
          },
          recovery: {
            dimension: 'recovery',
            available: false,
            status: 'insufficient_data',
            value: null,
            unit: 'fraction_[0..1]',
            formula: 'mean((x_end_or_rec - x_peak) / (x_pre - x_peak))',
            interpretation: 'Insufficient pre-event data.',
          },
          stability: {
            dimension: 'stability',
            available: true,
            status: 'completed',
            value: 0.51,
            unit: 'dimensionless_(0..1]',
            formula: '1 / (1 + std(standardized_deseasonalized_residuals))',
            interpretation: 'Dimensionless variance.',
          },
          sensitivity: {
            dimension: 'sensitivity',
            available: true,
            status: 'completed',
            value: 0.0024,
            unit: 'dimensionless/mm/month',
            formula: 'OLS slope of response anomaly against forcing driver anomaly',
            interpretation: 'Non-causal co-variation.',
          },
          composite_tri: {
            status: 'unavailable_unvalidated',
            value: null,
            reason: 'TRI weights withheld until calibrated.',
          },
        },
      ],
      uncertainty: {
        data_quality_confidence: 'high',
        data_quality_rationale: '95% valid.',
        statistical_confidence: 'moderate',
        statistical_rationale: 'Moderate sample span.',
        scientific_confidence: 'moderate',
        scientific_rationale: 'Proxy-only indicator.',
        methodological_limitations: ['Remote sensing proxy only.'],
      },
      provenance: {
        input_digest_sha256: 'abc123',
        config_digest_sha256: 'def456',
        generated_at_utc: '2026-11-15T10:00:00Z',
        dataset_lineage: [{ dataset_id: 'mod13-poly' }],
        methods_invoked: [
          { method_id: 'resilience_dimensions', version: '1.1.0', name: 'Resilience' },
        ],
        package_versions: { numpy: '2.2.0' },
      },
    })

    expect(parsed).not.toBeNull()
    expect(parsed?.status).toBe('completed_partial')
    expect(parsed?.qualityReports[0]?.qaScreenedOutCount).toBe(3)
    expect(parsed?.resilience[0]?.resistance?.eventValues[0]?.peakNegativeZscore).toBe(-3.0)
    expect(parsed?.resilience[0]?.recovery?.status).toBe('insufficient_data')
    expect(parsed?.resilience[0]?.sensitivity?.unit).toBe('dimensionless/mm/month')
    expect(parsed?.resilience[0]?.compositeTriStatus).toBe('unavailable_unvalidated')
    expect(parsed?.provenance?.inputDigestSha256).toBe('abc123')
    expect(parseScientificAssessmentResult(null)).toBeNull()
  })

  it('calls assessments endpoints and surfaces HTTP/API errors via ApiError', async () => {
    const getSpy = vi.spyOn(apiFetchClient, 'GET')
    const postSpy = vi.spyOn(apiFetchClient, 'POST')

    getSpy.mockResolvedValueOnce({
      data: [
        {
          methodId: 'mann_kendall',
          version: '1.0.0',
          name: 'Mann-Kendall',
          priority: 'P0',
          implemented: true,
          formulaSummary: 'tau',
          assumptions: [],
          limitations: [],
          reference: 'Kendall',
        },
      ],
      response: new Response(null, { status: 200 }),
    } as never)
    const methods = await fetchAssessmentMethods()
    expect(methods[0]?.methodId).toBe('mann_kendall')
    expect(getSpy).toHaveBeenCalledWith('/api/v1/assessments/methods')

    getSpy.mockResolvedValueOnce({
      error: { detail: 'Not authenticated' },
      response: new Response(null, { status: 401 }),
    } as never)
    await expect(fetchAssessments()).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      detail: 'Not authenticated',
    })

    postSpy.mockResolvedValueOnce({
      data: {
        id: 'a-1',
        ownerId: 'u-1',
        regionId: null,
        title: 'Test',
        status: 'queued',
        ghsDatasetIds: [],
        errorMessage: null,
        createdAt: '2026-11-15T10:00:00Z',
        updatedAt: '2026-11-15T10:00:00Z',
        completedAt: null,
        requestConfig: {},
        result: null,
        artifactPaths: {},
      },
      response: new Response(null, { status: 201 }),
    } as never)
    const created = await createAssessment({
      title: 'Test',
      executeNow: false,
      requestConfig: {},
    })
    expect(created.status).toBe('queued')
    expect(postSpy).toHaveBeenCalledWith('/api/v1/assessments', {
      body: { title: 'Test', executeNow: false, requestConfig: {} },
    })

    postSpy.mockResolvedValueOnce({
      data: {
        id: 'a-1',
        ownerId: 'u-1',
        regionId: null,
        title: 'Test',
        status: 'completed',
        ghsDatasetIds: [],
        errorMessage: null,
        createdAt: '2026-11-15T10:00:00Z',
        updatedAt: '2026-11-15T10:00:05Z',
        completedAt: '2026-11-15T10:00:05Z',
        requestConfig: {},
        result: { status: 'completed' },
        artifactPaths: {},
      },
      response: new Response(null, { status: 200 }),
    } as never)
    const executed = await executeAssessment('a-1')
    expect(executed.status).toBe('completed')
    expect(postSpy).toHaveBeenCalledWith('/api/v1/assessments/{assessment_id}/execute', {
      params: { path: { assessment_id: 'a-1' } },
    })

    getSpy.mockResolvedValueOnce({
      error: { detail: 'GHS unreachable' },
      response: new Response(null, { status: 502 }),
    } as never)
    await expect(fetchAssessmentDetail('a-1')).rejects.toMatchObject({
      name: 'ApiError',
      status: 502,
      detail: 'GHS unreachable',
    })

    getSpy.mockRejectedValueOnce(new Error('connect ECONNREFUSED'))
    await expect(fetchAssessmentDetail('a-1')).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
    })
  })

  it('parses temporalSeries, baselines, anomalies, and crossVariable from scientific results', () => {
    const parsed = parseScientificAssessmentResult({
      assessment_id: 'assess-ts-01',
      status: 'completed',
      temporal_series: [
        {
          dataset_id: 'ds-1',
          variable_name: 'NDVI',
          units: 'index',
          cadence: 'monthly',
          aggregation_operator: 'mean',
          timestamps: ['2024-01-01T00:00:00Z', '2024-02-01T00:00:00Z'],
          values: [0.62, 0.58],
          coverage_fractions: [1.0, 0.92],
          interpolated_indices: [1],
          warnings: [],
        },
      ],
      baselines: [
        {
          dataset_id: 'ds-1',
          variable_name: 'NDVI',
          units: 'index',
          baseline_type: 'monthly_climatology',
          bin_means: [0.64, 0.61],
          bin_stds: [0.05, 0.04],
          bin_counts: [5, 5],
          warnings: [],
        },
      ],
      anomalies: [
        {
          dataset_id: 'ds-1',
          variable_name: 'NDVI',
          units: 'index',
          timestamps: ['2024-01-01T00:00:00Z', '2024-02-01T00:00:00Z'],
          raw_anomalies: [-0.02, -0.03],
          standard_zscores: [-0.4, -0.75],
          robust_zscores: [-0.35, -0.8],
          persistent_runs: [
            {
              start_timestamp: '2024-02-01T00:00:00Z',
              end_timestamp: '2024-02-01T00:00:00Z',
              duration_steps: 1,
              peak_zscore: -0.75,
              severity: 'moderate',
            },
          ],
          warnings: [],
        },
      ],
      cross_variable: [
        {
          x_variable: 'PRECIP',
          y_variable: 'NDVI',
          pearson_r: 0.71,
          spearman_rho: 0.68,
          lag_steps: 1,
          p_value: 0.012,
          sample_count: 24,
          caveat: 'Observational correlation only.',
          warnings: [],
        },
      ],
    })

    expect(parsed).not.toBeNull()
    expect(parsed?.temporalSeries[0]).toMatchObject({
      datasetId: 'ds-1',
      variableName: 'NDVI',
      cadence: 'monthly',
      values: [0.62, 0.58],
      interpolatedIndices: [1],
    })
    expect(parsed?.baselines[0]).toMatchObject({
      baselineType: 'monthly_climatology',
      binMeans: [0.64, 0.61],
      binCounts: [5, 5],
    })
    expect(parsed?.anomalies[0]).toMatchObject({
      standardZscores: [-0.4, -0.75],
      robustZscores: [-0.35, -0.8],
    })
    expect(parsed?.anomalies[0]?.persistentRuns[0]?.severity).toBe('moderate')
    expect(parsed?.crossVariable[0]).toMatchObject({
      xVariable: 'PRECIP',
      yVariable: 'NDVI',
      pearsonR: 0.71,
      lagSteps: 1,
      sampleCount: 24,
    })
  })

  it('calls dev-session auth, data-sources discovery/ingestion/datasets, and comparison endpoints', async () => {
    const getSpy = vi.spyOn(apiFetchClient, 'GET')
    const postSpy = vi.spyOn(apiFetchClient, 'POST')

    postSpy.mockResolvedValueOnce({
      data: {
        accessToken: 'dev-jwt-token',
        tokenType: 'bearer',
        user: {
          id: 'u-dev',
          githubId: 0,
          githubLogin: 'terra-dev',
          displayName: 'Local Developer',
          avatarUrl: null,
          email: null,
          createdAt: '2026-11-15T10:00:00Z',
          updatedAt: '2026-11-15T10:00:00Z',
        },
      },
      response: new Response(null, { status: 200 }),
    } as never)
    const session = await loginDevSession()
    expect(session.user.githubLogin).toBe('terra-dev')
    expect(postSpy).toHaveBeenCalledWith('/api/v1/auth/dev-session')

    getSpy.mockResolvedValueOnce({
      data: [
        {
          provider: 'nasa_power',
          title: 'NASA POWER',
          enabled: true,
          authRequired: false,
          authConfigured: true,
          authMechanism: 'public',
          status: 'ready',
          supportsDiscovery: true,
          registeredProducts: ['POWER_DAILY'],
          products: [],
        },
      ],
      response: new Response(null, { status: 200 }),
    } as never)
    const providers = await fetchProviders()
    expect(providers[0]?.provider).toBe('nasa_power')
    expect(getSpy).toHaveBeenCalledWith('/api/v1/data-sources/providers')

    postSpy.mockResolvedValueOnce({
      data: {
        provider: 'nasa_power',
        product: 'POWER_DAILY',
        count: 1,
        bbox: [24.0, 48.0, 25.0, 49.0],
        observations: [
          {
            observationId: 'g-1',
            provider: 'nasa_power',
            product: 'POWER_DAILY',
            productVersion: '9.0',
            title: 'NASA POWER window',
            timeStart: '2024-01-01T00:00:00Z',
            timeEnd: '2024-01-31T23:59:59Z',
            bbox: [24.0, 48.0, 25.0, 49.0],
            queryMode: 'point',
            accessHint: 'public',
          },
        ],
      },
      response: new Response(null, { status: 200 }),
    } as never)
    const discovery = await discoverObservations({
      provider: 'nasa_power',
      product: 'POWER_DAILY',
      startTime: '2024-01-01T00:00:00Z',
      endTime: '2024-01-31T23:59:59Z',
      limit: 20,
    })
    expect(discovery.count).toBe(1)
    expect(postSpy).toHaveBeenCalledWith('/api/v1/data-sources/discover', {
      body: {
        provider: 'nasa_power',
        product: 'POWER_DAILY',
        startTime: '2024-01-01T00:00:00Z',
        endTime: '2024-01-31T23:59:59Z',
        limit: 20,
      },
    })

    postSpy.mockResolvedValueOnce({
      data: {
        id: 'op-1',
        regionId: null,
        ghsJobId: 'job-1',
        provider: 'nasa_power',
        product: 'POWER_DAILY',
        status: 'pending',
        progressPct: 0,
        datasetId: null,
        errorMessage: null,
        errorCategory: null,
        requestSummary: {},
        datasetSummary: null,
        createdAt: '2026-11-15T10:00:00Z',
        updatedAt: '2026-11-15T10:00:00Z',
        completedAt: null,
      },
      response: new Response(null, { status: 202 }),
    } as never)
    const operation = await startIngestion({
      provider: 'nasa_power',
      product: 'POWER_DAILY',
      startTime: '2024-01-01T00:00:00Z',
      endTime: '2024-01-31T23:59:59Z',
      maxGranules: 24,
      executeNow: false,
    })
    expect(operation.ghsJobId).toBe('job-1')
    expect(postSpy).toHaveBeenCalledWith('/api/v1/data-sources/ingestions', {
      body: {
        provider: 'nasa_power',
        product: 'POWER_DAILY',
        startTime: '2024-01-01T00:00:00Z',
        endTime: '2024-01-31T23:59:59Z',
        maxGranules: 24,
        executeNow: false,
      },
    })

    getSpy.mockResolvedValueOnce({
      data: [
        {
          datasetId: 'ds-99',
          sourceId: 'src-power-99',
          provider: 'nasa_power',
          product: 'POWER_DAILY',
          variables: ['T2M'],
          temporalStart: '2024-01-01T00:00:00Z',
          temporalEnd: '2024-01-31T23:59:59Z',
          temporalCadence: 'daily',
          observationCount: 31,
          validFraction: 1,
          warnings: [],
          timeSeriesPreviews: [],
        },
      ],
      response: new Response(null, { status: 200 }),
    } as never)
    const datasets = await fetchPreparedDatasets()
    expect(datasets[0]?.datasetId).toBe('ds-99')
    expect(getSpy).toHaveBeenCalledWith('/api/v1/data-sources/datasets', {
      params: { query: undefined },
    })

    postSpy.mockResolvedValueOnce({
      data: {
        primary: {
          id: 'a-1',
          ownerId: 'u-1',
          regionId: null,
          title: 'A',
          status: 'completed',
          ghsDatasetIds: ['ds-1'],
          errorMessage: null,
          createdAt: '2026-11-15T10:00:00Z',
          updatedAt: '2026-11-15T10:00:00Z',
          completedAt: '2026-11-15T10:01:00Z',
          requestConfig: {},
          result: {},
          artifactPaths: {},
        },
        comparison: {
          id: 'a-2',
          ownerId: 'u-1',
          regionId: null,
          title: 'B',
          status: 'completed',
          ghsDatasetIds: ['ds-2'],
          errorMessage: null,
          createdAt: '2026-11-15T10:00:00Z',
          updatedAt: '2026-11-15T10:00:00Z',
          completedAt: '2026-11-15T10:01:00Z',
          requestConfig: {},
          result: {},
          artifactPaths: {},
        },
        sharedVariables: ['NDVI'],
        primaryOnlyVariables: [],
        comparisonOnlyVariables: [],
        variableComparisons: [],
        compatibilityWarnings: [],
        methodologyNotes: ['Composite TRI remains disabled'],
      },
      response: new Response(null, { status: 200 }),
    } as never)
    const comparison = await compareAssessments({
      primaryAssessmentId: 'a-1',
      comparisonAssessmentId: 'a-2',
    })
    expect(comparison.sharedVariables).toEqual(['NDVI'])
    expect(postSpy).toHaveBeenCalledWith('/api/v1/assessments/compare', {
      body: {
        primaryAssessmentId: 'a-1',
        comparisonAssessmentId: 'a-2',
      },
    })
  })
})
