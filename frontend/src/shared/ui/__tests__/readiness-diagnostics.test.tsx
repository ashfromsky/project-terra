import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ParsedReadinessReport } from '../../api/assessments'
import { ReadinessDiagnosticsPanel } from '../readiness-diagnostics'

function makeSampleReport(overallStatus: 'ready' | 'partial' | 'insufficient'): ParsedReadinessReport {
  return {
    specVersion: '1.0.0',
    evaluatedAtUtc: '2026-11-15T18:00:00Z',
    overallStatus,
    summary: 'Historical baseline covers 1.0 years; minimum 3 years required for climate anomalies.',
    datasets: [
      {
        datasetId: 'ds-power-1',
        sourceId: 'nasa_power',
        product: 'POWER_AG_DAILY',
        variables: ['T2M'],
        nativeCadence: 'daily',
        targetCadence: 'monthly',
        observationStart: '2024-01-01T00:00:00Z',
        observationEnd: '2024-12-31T00:00:00Z',
        spanYears: 1.0,
        rawStepCount: 12,
        validQaCount: 12,
        validFraction: 1.0,
        qaLayersPresent: ['ALLSKY_SFC_SW_DWN_QA'],
        hasGridStack: false,
        minQaFractionRequired: 0.7,
        minStepCoverageRequired: 0.75,
        minTrendSamplesRequired: 18,
        minBaselineYearsRequired: 3,
        status: 'insufficient',
        notes: [],
      },
    ],
    criteria: [
      {
        criterionId: 'qa-1',
        category: 'qa',
        datasetId: 'ds-power-1',
        variableName: 'T2M',
        stageOrMetric: 'quality_screening',
        title: 'QA Screening Coverage',
        requiredSummary: '>= 70% valid QA pixels',
        actualSummary: '100.0% valid (12/12)',
        requiredValue: 0.7,
        actualValue: 1.0,
        unit: 'fraction',
        status: 'passed',
        scientificRationale: 'NASA POWER meteorological time series QA screening.',
        missingGap: null,
        remediation: null,
        specVersion: '1.0.0',
      },
      {
        criterionId: 'trend-1',
        category: 'trend',
        datasetId: 'ds-power-1',
        variableName: 'T2M',
        stageOrMetric: 'trends',
        title: 'Mann-Kendall Sample Size',
        requiredSummary: '>= 18 monthly observations',
        actualSummary: '12 monthly observations',
        requiredValue: 18,
        actualValue: 12,
        unit: 'steps',
        status: 'warning',
        scientificRationale: 'Seasonal trend test power degrades below 18 steps.',
        missingGap: 'Need 6 additional monthly steps for trend significance.',
        remediation: 'Extend ingestion span to >= 2 years.',
        specVersion: '1.0.0',
      },
      {
        criterionId: 'baseline-1',
        category: 'baseline',
        datasetId: 'ds-power-1',
        variableName: 'T2M',
        stageOrMetric: 'baseline',
        title: 'Historical Baseline Span',
        requiredSummary: '>= 3 reference years prior to analysis window',
        actualSummary: '0.0 reference years (non-overlapping)',
        requiredValue: 3,
        actualValue: 0,
        unit: 'years',
        status: 'failed',
        scientificRationale: 'Out-of-sample baseline prevents data leakage.',
        missingGap: 'Missing historical years 2021-2023 prior to 2024 analysis.',
        remediation: 'Click Auto-Provision Missing Data to fetch 2020-2024.',
        specVersion: '1.0.0',
      },
    ],
    metrics: [
      {
        metricId: 'quality_screening',
        label: 'Quality Screening',
        priority: 'P0',
        required: true,
        status: 'available',
        blockingCriteria: [],
        reason: 'All quality checks passed.',
        remediation: null,
      },
      {
        metricId: 'baseline',
        label: 'Baseline Climatology',
        priority: 'P0',
        required: true,
        status: 'unavailable',
        blockingCriteria: ['baseline-1'],
        reason: 'Zero reference observations precede analysis start.',
        remediation: 'Click Auto-Provision Missing Data to fetch 2020-2024.',
      },
      {
        metricId: 'composite_tri',
        label: 'Composite TRI',
        priority: 'P2',
        required: false,
        status: 'deferred',
        blockingCriteria: [],
        reason: 'Unvalidated experimental index withheld from authoritative outputs.',
        remediation: null,
      },
    ],
    recommendedActions: ['Click Auto-Provision Missing Data to fetch 2020-2024.'],
    suggestedWindowStart: '2020-01-01T00:00:00Z',
    suggestedWindowEnd: '2023-12-31T00:00:00Z',
  }
}

describe('ReadinessDiagnosticsPanel', () => {
  it('renders criteria Passed/Warning/Failed, required vs actual, remediations, and metric availability in pre-run mode', () => {
    const html = renderToStaticMarkup(
      <ReadinessDiagnosticsPanel
        readiness={makeSampleReport('insufficient')}
        mode="pre_run"
        onApplySuggestedWindow={() => {}}
      />,
    )

    expect(html).toContain('Pre-Run Adaptive Data Readiness')
    expect(html).toContain('Passed')
    expect(html).toContain('Warning')
    expect(html).toContain('Failed')
    expect(html).toContain('&gt;= 3 reference years prior to analysis window')
    expect(html).toContain('0.0 reference years (non-overlapping)')
    expect(html).toContain('Missing historical years 2021-2023 prior to 2024 analysis.')
    expect(html).toContain('Click Auto-Provision Missing Data to fetch 2020-2024.')
    expect(html).toContain('Apply Suggested Baseline Window')
    expect(html).toContain('Available')
    expect(html).toContain('Unavailable')
    expect(html).toContain('Deferred')
  })

  it('renders detailed post-run limitation diagnostics instead of opaque status labels', () => {
    const html = renderToStaticMarkup(
      <ReadinessDiagnosticsPanel readiness={makeSampleReport('partial')} mode="post_run" />,
    )

    expect(html).toContain('Data Readiness &amp; Metric Limitation Diagnostics')
    expect(html).toContain('Zero reference observations precede analysis start.')
    expect(html).not.toContain('Apply Suggested Baseline Window')
  })
})
