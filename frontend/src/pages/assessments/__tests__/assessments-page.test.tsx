import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import AssessmentsPage from '../AssessmentsPage'

vi.mock('../../../shared/ui/chart', () => ({
  Chart: () => <div data-testid="mock-chart" />,
}))

vi.mock('../../../shared/api/auth', () => ({
  useCurrentUserQuery: () => ({
    data: { id: 'usr-1', email: 'scientist@terra.local', githubLogin: 'terra-researcher' },
    isPending: false,
    isError: false,
  }),
}))

vi.mock('../../../shared/api/regions', () => ({
  useRegionsQuery: () => ({
    data: [
      {
        id: 'reg-carpathian',
        name: 'Carpathian Forest Reserve',
        role: 'aoi',
        approxAreaKm2: 4250,
        sourceCrs: 'EPSG:4326',
        bbox: [24.0, 48.0, 25.5, 49.2],
        centroid: [24.75, 48.6],
        geometry: { type: 'Polygon', coordinates: [] },
      },
    ],
    isPending: false,
    isError: false,
  }),
}))

vi.mock('../../../shared/api/data-sources', () => ({
  usePreparedDatasetsQuery: () => ({
    data: [
      {
        datasetId: 'ds-modis-ndvi',
        provider: 'NASA LP DAAC',
        product: 'MOD13Q1',
        variables: ['NDVI'],
        observationCount: 72,
        temporalStart: '2021-01-01T00:00:00Z',
        temporalEnd: '2023-12-31T00:00:00Z',
      },
    ],
    isPending: false,
    isError: false,
  }),
  useAutoProvisionMutation: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}))

vi.mock('../../../shared/api/assessments', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../shared/api/assessments')>()
  return {
    ...actual,
    useAssessmentsQuery: () => ({
      data: [
        {
          id: 'asmt-1',
          title: 'Carpathian NDVI 2021–2023',
          regionId: 'reg-carpathian',
          status: 'completed',
          createdAt: '2026-11-15T12:00:00Z',
          updatedAt: '2026-11-15T12:05:00Z',
        },
      ],
      isPending: false,
      isError: false,
    }),
    useAssessmentDetailQuery: (id: string | null) => ({
      data:
        id === 'asmt-1'
          ? {
              id: 'asmt-1',
              title: 'Carpathian NDVI 2021–2023',
              regionId: 'reg-carpathian',
              status: 'completed',
              createdAt: '2026-11-15T12:00:00Z',
              completedAt: '2026-11-15T12:05:00Z',
              ghsDatasetIds: ['ds-modis-ndvi'],
              artifactPaths: {},
              requestConfig: {
                analysis_start: '2021-01-01T00:00:00Z',
                analysis_end: '2023-12-31T23:59:59Z',
                target_cadence: 'monthly',
              },
              result: {
                spec_version: '1.0.0',
                evaluated_at_utc: '2026-11-15T12:05:00Z',
                resilience: [
                  {
                    dataset_id: 'ds-modis-ndvi',
                    variable_name: 'NDVI',
                    composite_tri: {
                      status: 'withheld',
                      reason: 'Composite TRI withheld per ADR-0004 scientific rigor.',
                    },
                    resistance: {
                      dimension: 'resistance',
                      status: 'computed',
                      available: true,
                      value: 0.8124,
                      unit: 'fraction',
                      formula: 'min(y_disturbed) / baseline',
                      interpretation: 'Vegetation canopy retained 81.2% greenness during drought.',
                      event_values: [],
                      limitations: [],
                    },
                    recovery: {
                      dimension: 'recovery',
                      status: 'computed',
                      available: true,
                      value: 45.0,
                      unit: 'days',
                      formula: 't_recovered - t_min',
                      interpretation: 'Return to baseline threshold within 45 days.',
                      event_values: [],
                      limitations: [],
                    },
                    stability: {
                      dimension: 'stability',
                      status: 'computed',
                      available: true,
                      value: 0.0412,
                      unit: 'variance',
                      formula: 'var(y_post)',
                      interpretation: 'Low post-event variance indicative of high stability.',
                      event_values: [],
                      limitations: [],
                    },
                    sensitivity: {
                      dimension: 'sensitivity',
                      status: 'computed',
                      available: true,
                      value: 0.284,
                      unit: 'dNDVI/dSPEI',
                      formula: 'cov(NDVI, SPEI) / var(SPEI)',
                      interpretation: 'Moderate vegetation sensitivity to precipitation deficits.',
                      event_values: [],
                      limitations: [],
                    },
                  },
                ],
                trends: [
                  {
                    dataset_id: 'ds-modis-ndvi',
                    variable_name: 'NDVI',
                    variant: 'standard',
                    valid_count: 36,
                    sample_count: 36,
                    direction: 'increasing',
                    sens_slope: 0.0024,
                    slope_unit: 'yr⁻¹',
                    p_value: 0.012,
                  },
                ],
                cross_variable_associations: [],
                temporal_series: [],
                anomalies: [],
                baselines: [],
                quality_reports: [],
                readiness: null,
                uncertainty: null,
                provenance: null,
                warnings: [],
                errors: [],
              },
            }
          : null,
      isPending: false,
      isError: false,
    }),
    useAssessmentReadinessQuery: () => ({
      data: null,
      isPending: false,
      isError: false,
    }),
    useAssessmentMethodsQuery: () => ({
      data: [
        {
          methodId: 'resistance',
          name: 'Ecosystem Resistance',
          priority: 'P0',
          implemented: true,
          version: '1.0.0',
          formulaSummary: 'R = min(obs) / baseline',
          limitations: ['Requires clear drought event detection'],
          reference: 'Nimmo et al. 2015',
        },
      ],
      isPending: false,
      isError: false,
    }),
    useCreateAssessmentMutation: () => ({
      mutateAsync: vi.fn(),
      isPending: false,
    }),
    useExecuteAssessmentMutation: () => ({
      mutateAsync: vi.fn(),
      isPending: false,
    }),
  }
})

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      {ui}
    </QueryClientProvider>,
  )
}

describe('AssessmentsPage workflow and hierarchy', () => {
  it('renders rail mode tabs with Saved Runs count and + New Assessment switch', () => {
    const html = renderWithClient(
      <MemoryRouter initialEntries={['/assessments']}>
        <AssessmentsPage />
      </MemoryRouter>,
    )

    expect(html).toContain('Saved Runs')
    expect(html).toContain('sci-rail__tab-count')
    expect(html).toContain('+ New Assessment')
    expect(html).toContain('Carpathian NDVI 2021–2023')
  })

  it('outputs calculated Primary Resilience Dimensions and Trends FIRST, before Geographic Context', () => {
    const html = renderWithClient(
      <MemoryRouter initialEntries={['/assessments?assessmentId=asmt-1']}>
        <AssessmentsPage />
      </MemoryRouter>,
    )

    expect(html).toContain('Resilience Dimensions · NDVI')
    expect(html).toContain('0.8124')
    expect(html).toContain('45.0000')
    expect(html).toContain('Trends (Mann-Kendall / Sen&#x27;s Slope)')
    expect(html).toContain('increasing')
    expect(html).toContain('Selected AOI &amp; Analysis Period')

    // Verify ordering: Resilience Dimensions index < Selected AOI index
    const resilienceIndex = html.indexOf('Resilience Dimensions · NDVI')
    const trendsIndex = html.indexOf('Trends (Mann-Kendall / Sen&#x27;s Slope)')
    const aoiIndex = html.indexOf('Selected AOI &amp; Analysis Period')

    expect(resilienceIndex).toBeGreaterThan(-1)
    expect(trendsIndex).toBeGreaterThan(-1)
    expect(aoiIndex).toBeGreaterThan(-1)

    // Primary metrics MUST be output first!
    expect(resilienceIndex).toBeLessThan(aoiIndex)
    expect(trendsIndex).toBeLessThan(aoiIndex)
  })

  it('renders creation form when ?create=true is in search parameters', () => {
    const html = renderWithClient(
      <MemoryRouter initialEntries={['/assessments?create=true']}>
        <AssessmentsPage />
      </MemoryRouter>,
    )

    expect(html).toContain('New Assessment')
    expect(html).toContain('Target &amp; Region')
    expect(html).toContain('Analysis Profile Preset')
    expect(html).toContain('Quick')
    expect(html).toContain('Seasonal')
    expect(html).toContain('Historical')
    expect(html).toContain('Advanced Parameters &amp; Fine-Tuning')
  })
})
