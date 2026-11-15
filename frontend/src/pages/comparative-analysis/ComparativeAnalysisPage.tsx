import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  parseScientificAssessmentResult,
  useAssessmentsQuery,
  useCompareAssessmentsMutation,
  type AssessmentSummaryResponse,
} from '../../shared/api/assessments'
import { useCurrentUserQuery } from '../../shared/api/auth'
import { ApiError } from '../../shared/api/client'
import { useRegionsQuery } from '../../shared/api/regions'
import { APP_ROUTES } from '../../shared/config/routes'
import { buildComparisonOverlayChartOption } from '../../shared/lib/scientific-charts'
import { AuthActionBanner } from '../../shared/ui/auth-action-banner'
import { Button } from '../../shared/ui/button'
import { Chart } from '../../shared/ui/chart'
import { StatusBadge, type StatusBadgeTone } from '../../shared/ui/status-badge'

function statusTone(status: string): StatusBadgeTone {
  switch (status) {
    case 'completed':
      return 'success'
    case 'completed_partial':
    case 'queued':
    case 'running':
      return 'warning'
    case 'insufficient_data':
    case 'failed':
      return 'error'
    default:
      return 'neutral'
  }
}

function formatNumber(val: number | null | undefined, digits = 3): string {
  if (val === null || val === undefined || !Number.isFinite(val)) return '—'
  return val.toFixed(digits)
}

function formatDelta(val: number | null | undefined, digits = 3): string {
  if (val === null || val === undefined || !Number.isFinite(val)) return '—'
  const sign = val > 0 ? '+' : ''
  return `${sign}${val.toFixed(digits)}`
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  return parsed.toISOString().slice(0, 10)
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return `${err.message} (HTTP ${err.status})`
  }
  if (err instanceof Error) return err.message
  return 'Unexpected error executing comparison.'
}

function isComparableAssessment(item: AssessmentSummaryResponse): boolean {
  return item.status === 'completed' || item.status === 'completed_partial'
}

export default function ComparativeAnalysisPage() {
  const [searchParams] = useSearchParams()
  const initialPrimaryId = searchParams.get('primaryId')
  const initialComparisonId = searchParams.get('comparisonId')

  const [primaryOverrideId, setPrimaryOverrideId] = useState<string | null>(initialPrimaryId)
  const [comparisonOverrideId, setComparisonOverrideId] = useState<string | null>(
    initialComparisonId,
  )
  const [selectedVariable, setSelectedVariable] = useState<string | null>(null)

  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)

  const assessmentsQuery = useAssessmentsQuery(isAuthenticated)
  const regionsQuery = useRegionsQuery(isAuthenticated)
  const compareMutation = useCompareAssessmentsMutation()

  const regionNameById = useMemo(() => {
    const map = new Map<string, string>()
    for (const region of regionsQuery.data ?? []) {
      map.set(region.id, region.name)
    }
    return map
  }, [regionsQuery.data])

  const allAssessments = useMemo(
    () => assessmentsQuery.data ?? [],
    [assessmentsQuery.data],
  )
  const comparableAssessments = useMemo(
    () => allAssessments.filter(isComparableAssessment),
    [allAssessments],
  )

  const effectivePrimaryId = useMemo(() => {
    if (
      primaryOverrideId &&
      comparableAssessments.some((item) => item.id === primaryOverrideId)
    ) {
      return primaryOverrideId
    }
    return comparableAssessments[0]?.id ?? ''
  }, [comparableAssessments, primaryOverrideId])

  const effectiveComparisonId = useMemo(() => {
    if (
      comparisonOverrideId &&
      comparableAssessments.some((item) => item.id === comparisonOverrideId) &&
      comparisonOverrideId !== effectivePrimaryId
    ) {
      return comparisonOverrideId
    }
    return (
      comparableAssessments.find((item) => item.id !== effectivePrimaryId)?.id ?? ''
    )
  }, [comparableAssessments, comparisonOverrideId, effectivePrimaryId])

  const primarySummary =
    comparableAssessments.find((item) => item.id === effectivePrimaryId) ?? null
  const comparisonSummary =
    comparableAssessments.find((item) => item.id === effectiveComparisonId) ?? null

  const canRunComparison =
    isAuthenticated &&
    Boolean(effectivePrimaryId) &&
    Boolean(effectiveComparisonId) &&
    effectivePrimaryId !== effectiveComparisonId &&
    !compareMutation.isPending

  const comparisonData = compareMutation.data ?? null

  const parsedPrimaryResult = useMemo(
    () => (comparisonData ? parseScientificAssessmentResult(comparisonData.primary.result) : null),
    [comparisonData],
  )
  const parsedComparisonResult = useMemo(
    () =>
      comparisonData
        ? parseScientificAssessmentResult(comparisonData.comparison.result)
        : null,
    [comparisonData],
  )

  const activeVariable = useMemo(() => {
    const shared = comparisonData?.sharedVariables ?? []
    if (selectedVariable && shared.includes(selectedVariable)) {
      return selectedVariable
    }
    return shared[0] ?? ''
  }, [comparisonData, selectedVariable])

  const overlayChartOption = useMemo(() => {
    if (!comparisonData || !activeVariable || !parsedPrimaryResult || !parsedComparisonResult) {
      return null
    }
    const primarySeries = parsedPrimaryResult.temporalSeries.find(
      (series) => series.variableName === activeVariable,
    )
    const comparisonSeries = parsedComparisonResult.temporalSeries.find(
      (series) => series.variableName === activeVariable,
    )
    if (
      !primarySeries ||
      !comparisonSeries ||
      primarySeries.timestamps.length === 0 ||
      comparisonSeries.timestamps.length === 0
    ) {
      return null
    }
    return buildComparisonOverlayChartOption({
      variableName: activeVariable,
      units: primarySeries.units || comparisonSeries.units,
      primaryLabel: `A · ${comparisonData.primary.title}`,
      comparisonLabel: `B · ${comparisonData.comparison.title}`,
      primaryTimestamps: primarySeries.timestamps,
      primaryValues: primarySeries.values,
      comparisonTimestamps: comparisonSeries.timestamps,
      comparisonValues: comparisonSeries.values,
    })
  }, [activeVariable, comparisonData, parsedComparisonResult, parsedPrimaryResult])

  const handleRunComparison = () => {
    if (!canRunComparison) return
    compareMutation.mutate({
      primaryAssessmentId: effectivePrimaryId,
      comparisonAssessmentId: effectiveComparisonId,
    })
  }

  return (
    <div className="workspace-page">
      <section className="workspace-context-bar" aria-label="Comparative analysis header">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading">
            Comparative Environmental Analysis
          </h1>
          <p className="workspace-context-bar__breadcrumb">
            Comparative Analysis / Paired Scientific Assessments / Trends &amp; Resilience Deltas
          </p>
        </div>
        <div className="workspace-context-bar__actions">
          <StatusBadge tone={comparisonData ? 'success' : 'neutral'}>
            {comparisonData
              ? `COMPARISON READY · ${comparisonData.sharedVariables.length} shared variable(s)`
              : `${comparableAssessments.length} COMPLETED ASSESSMENT(S)`}
          </StatusBadge>
          <Link to={APP_ROUTES.assessments} className="terra-link-reset">
            <Button variant="secondary">Back to Assessments</Button>
          </Link>
          {effectivePrimaryId ? (
            <Link
              to={`${APP_ROUTES.reports}?assessmentId=${encodeURIComponent(effectivePrimaryId)}`}
              className="terra-link-reset"
            >
              <Button variant="primary">Open Report</Button>
            </Link>
          ) : (
            <Link to={APP_ROUTES.reports} className="terra-link-reset">
              <Button variant="primary">Reports</Button>
            </Link>
          )}
        </div>
      </section>

      {!isAuthenticated && !currentUserQuery.isPending ? (
        <AuthActionBanner
          returnTo={APP_ROUTES.comparativeAnalysis}
          title="Sign in to compare your persisted Scientific Assessments"
          description="Paired comparisons run against your completed Scientific Assessment results via POST /api/v1/assessments/compare."
        />
      ) : null}

      <div className="sci-workspace-shell">
        <aside className="sci-rail" aria-label="Comparison selector">
          <section className="sci-panel">
            <div className="sci-panel__header">
              <div>
                <h2 className="sci-panel__title">Select Paired Assessments</h2>
                <p className="sci-panel__subtitle">
                  Compare trends and disaggregated resilience dimensions between two completed runs
                </p>
              </div>
            </div>

            {isAuthenticated && comparableAssessments.length < 2 ? (
              <div className="sci-banner sci-banner--neutral">
                <span>
                  Found {allAssessments.length} assessment(s), with{' '}
                  {comparableAssessments.length} completed. Run at least two assessments to
                  compare paired AOIs or time periods.
                </span>
              </div>
            ) : null}

            <div className="sci-form">
              <div className="sci-field">
                <label className="sci-label" htmlFor="compare-primary-select">
                  Assessment A (Primary)
                </label>
                <select
                  id="compare-primary-select"
                  className="sci-select"
                  value={effectivePrimaryId}
                  onChange={(event) => {
                    setPrimaryOverrideId(event.target.value)
                    compareMutation.reset()
                  }}
                  disabled={!isAuthenticated || comparableAssessments.length === 0}
                >
                  {comparableAssessments.length === 0 ? (
                    <option value="">No completed assessments</option>
                  ) : null}
                  {comparableAssessments.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title} ({item.status})
                    </option>
                  ))}
                </select>
              </div>

              <div className="sci-field">
                <label className="sci-label" htmlFor="compare-secondary-select">
                  Assessment B (Comparison)
                </label>
                <select
                  id="compare-secondary-select"
                  className="sci-select"
                  value={effectiveComparisonId}
                  onChange={(event) => {
                    setComparisonOverrideId(event.target.value)
                    compareMutation.reset()
                  }}
                  disabled={!isAuthenticated || comparableAssessments.length < 2}
                >
                  {comparableAssessments.length < 2 ? (
                    <option value="">Select a second completed assessment</option>
                  ) : null}
                  {comparableAssessments
                    .filter((item) => item.id !== effectivePrimaryId)
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.title} ({item.status})
                      </option>
                    ))}
                </select>
              </div>

              {primarySummary ? (
                <div className="workspace-aoi-card workspace-aoi-card--a">
                  <p className="workspace-aoi-card__overline">ASSESSMENT A</p>
                  <p className="workspace-aoi-card__name">{primarySummary.title}</p>
                  <p className="workspace-aoi-card__meta">
                    {primarySummary.regionId
                      ? regionNameById.get(primarySummary.regionId) ?? primarySummary.regionId
                      : 'Ad-hoc / no region link'}
                  </p>
                  <p className="workspace-aoi-card__coords">
                    Completed {formatDate(primarySummary.completedAt ?? primarySummary.createdAt)} ·{' '}
                    {primarySummary.ghsDatasetIds.length} dataset(s)
                  </p>
                </div>
              ) : null}

              {comparisonSummary ? (
                <div className="workspace-aoi-card workspace-aoi-card--b">
                  <p className="workspace-aoi-card__overline workspace-aoi-card__overline--b">
                    ASSESSMENT B
                  </p>
                  <p className="workspace-aoi-card__name">{comparisonSummary.title}</p>
                  <p className="workspace-aoi-card__meta">
                    {comparisonSummary.regionId
                      ? regionNameById.get(comparisonSummary.regionId) ??
                        comparisonSummary.regionId
                      : 'Ad-hoc / no region link'}
                  </p>
                  <p className="workspace-aoi-card__coords">
                    Completed{' '}
                    {formatDate(comparisonSummary.completedAt ?? comparisonSummary.createdAt)} ·{' '}
                    {comparisonSummary.ghsDatasetIds.length} dataset(s)
                  </p>
                </div>
              ) : null}

              <Button
                type="button"
                variant={canRunComparison ? 'primary' : 'disabled'}
                disabled={!canRunComparison}
                onClick={handleRunComparison}
              >
                {compareMutation.isPending ? 'Comparing Assessments…' : 'Run Comparison'}
              </Button>

              {compareMutation.isError ? (
                <div className="sci-banner sci-banner--error" role="alert">
                  <span>{describeError(compareMutation.error)}</span>
                </div>
              ) : null}
            </div>
          </section>

          <section className="sci-panel">
            <div className="sci-panel__header">
              <div>
                <h2 className="sci-panel__title">Methodological Guardrails</h2>
                <p className="sci-panel__subtitle">
                  Scientific comparison rules enforced by Core API
                </p>
              </div>
            </div>
            <ul className="workspace-spec-list">
              <li className="workspace-spec-item">
                <span className="workspace-spec-item__label">Resilience Policy</span>
                <span className="workspace-spec-item__value">
                  4 separated dimensions (Composite TRI disabled)
                </span>
              </li>
              <li className="workspace-spec-item">
                <span className="workspace-spec-item__label">Trend Inference</span>
                <span className="workspace-spec-item__value">
                  Mann–Kendall + Sen’s slope Δ (A − B)
                </span>
              </li>
              <li className="workspace-spec-item">
                <span className="workspace-spec-item__label">Attribution</span>
                <span className="workspace-spec-item__value">
                  Observational comparison only · No causal inference
                </span>
              </li>
            </ul>
          </section>
        </aside>

        <main className="sci-main-stack">
          {!comparisonData ? (
            <section className="sci-panel">
              <div className="sci-panel__header">
                <div>
                  <h2 className="sci-panel__title">Comparative Results Workspace</h2>
                  <p className="sci-panel__subtitle">
                    {comparableAssessments.length < 2
                      ? 'Two completed assessments are required before paired comparison can run.'
                      : 'Choose Assessment A and Assessment B on the left, then click Run Comparison.'}
                  </p>
                </div>
                <StatusBadge tone="neutral">Awaiting comparison</StatusBadge>
              </div>

              <div className="sci-kpi-grid">
                <article className="sci-dim-card">
                  <div className="sci-dim-card__head">
                    <span className="sci-dim-card__name">Completed Runs</span>
                    <StatusBadge tone="teal">Core DB</StatusBadge>
                  </div>
                  <p className="sci-dim-card__value">{comparableAssessments.length}</p>
                  <p className="sci-dim-card__note">
                    Out of {allAssessments.length} persisted assessment(s) in your workspace.
                  </p>
                </article>
                <article className="sci-dim-card">
                  <div className="sci-dim-card__head">
                    <span className="sci-dim-card__name">Dimensions Compared</span>
                    <StatusBadge tone="neutral">4 + Trend</StatusBadge>
                  </div>
                  <p className="sci-dim-card__value">5</p>
                  <p className="sci-dim-card__note">
                    Sen’s slope, Resistance, Recovery, Stability, Sensitivity (plus series mean).
                  </p>
                </article>
              </div>

              <div className="sci-btn-row">
                <Link to={APP_ROUTES.explore} className="terra-link-reset">
                  <Button variant="secondary">1. Draw AOI on Map</Button>
                </Link>
                <Link to={APP_ROUTES.dataSources} className="terra-link-reset">
                  <Button variant="secondary">2. Ingest NASA Observations</Button>
                </Link>
                <Link to={APP_ROUTES.assessments} className="terra-link-reset">
                  <Button variant="primary">3. Create &amp; Run Assessments</Button>
                </Link>
              </div>
            </section>
          ) : (
            <>
              {comparisonData.compatibilityWarnings.length > 0 ? (
                <div className="sci-banner sci-banner--warning" role="status">
                  <div>
                    <strong>Compatibility Warnings</strong>
                    <ul>
                      {comparisonData.compatibilityWarnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : null}

              <section className="sci-panel">
                <div className="sci-panel__header">
                  <div>
                    <h2 className="sci-panel__title">Paired Trajectory Overlay</h2>
                    <p className="sci-panel__subtitle">
                      Side-by-side temporal series across harmonized observations
                    </p>
                  </div>
                  <div className="sci-btn-row">
                    {comparisonData.sharedVariables.length > 0 ? (
                      <select
                        aria-label="Shared variable overlay"
                        className="sci-select"
                        value={activeVariable}
                        onChange={(event) => setSelectedVariable(event.target.value)}
                      >
                        {comparisonData.sharedVariables.map((variableName) => (
                          <option key={variableName} value={variableName}>
                            {variableName}
                          </option>
                        ))}
                      </select>
                    ) : null}
                    <StatusBadge tone={statusTone(comparisonData.primary.status)}>
                      A: {comparisonData.primary.status}
                    </StatusBadge>
                    <StatusBadge tone={statusTone(comparisonData.comparison.status)}>
                      B: {comparisonData.comparison.status}
                    </StatusBadge>
                  </div>
                </div>

                {overlayChartOption ? (
                  <Chart option={overlayChartOption} className="sci-chart-box" />
                ) : (
                  <div className="sci-banner sci-banner--neutral">
                    <span>
                      {comparisonData.sharedVariables.length === 0
                        ? 'No shared variables overlap between Assessment A and Assessment B.'
                        : 'Time-series values are unavailable in one or both stored results for overlay plotting; inspect quantitative deltas below.'}
                    </span>
                  </div>
                )}

                {comparisonData.primaryOnlyVariables.length > 0 ||
                comparisonData.comparisonOnlyVariables.length > 0 ? (
                  <div className="sci-btn-row">
                    {comparisonData.primaryOnlyVariables.length > 0 ? (
                      <span className="sci-code-chip">
                        Only in A: {comparisonData.primaryOnlyVariables.join(', ')}
                      </span>
                    ) : null}
                    {comparisonData.comparisonOnlyVariables.length > 0 ? (
                      <span className="sci-code-chip">
                        Only in B: {comparisonData.comparisonOnlyVariables.join(', ')}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </section>

              <section className="sci-panel">
                <div className="sci-panel__header">
                  <div>
                    <h2 className="sci-panel__title">Statistical &amp; Resilience Deltas (A − B)</h2>
                    <p className="sci-panel__subtitle">
                      Separated trend and resilience comparisons per shared variable (Primary A − Comparison B)
                    </p>
                  </div>
                </div>

                {comparisonData.variableComparisons.length === 0 ? (
                  <p className="workspace-config-rail__note">
                    No shared variables available to compute statistical deltas.
                  </p>
                ) : (
                  <div className="provenance-table-wrapper">
                    <table className="provenance-table" aria-label="Comparative statistical deltas">
                      <thead>
                        <tr>
                          <th scope="col">Variable</th>
                          <th scope="col">Mean (A / B / Δ)</th>
                          <th scope="col">Sen’s Slope (A / B / Δ)</th>
                          <th scope="col">Direction / p-val (A · B)</th>
                          <th scope="col">Resistance Δ</th>
                          <th scope="col">Recovery Δ</th>
                          <th scope="col">Stability Δ</th>
                          <th scope="col">Sensitivity Δ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {comparisonData.variableComparisons.map((row) => (
                          <tr key={row.variableName}>
                            <td className="provenance-table__primary">{row.variableName}</td>
                            <td>
                              {formatNumber(row.primaryMeanValue)} /{' '}
                              {formatNumber(row.comparisonMeanValue)} (
                              {formatDelta(row.meanValueDelta)})
                            </td>
                            <td>
                              {formatNumber(row.primarySensSlope, 4)} /{' '}
                              {formatNumber(row.comparisonSensSlope, 4)} (
                              {formatDelta(row.sensSlopeDelta, 4)}
                              {row.slopeUnit ? ` ${row.slopeUnit}` : ''})
                            </td>
                            <td>
                              {row.primaryDirection ?? '—'} (p={formatNumber(row.primaryPValue)}) ·{' '}
                              {row.comparisonDirection ?? '—'} (p=
                              {formatNumber(row.comparisonPValue)})
                            </td>
                            <td>{formatDelta(row.resistanceDelta)}</td>
                            <td>{formatDelta(row.recoveryDelta)}</td>
                            <td>{formatDelta(row.stabilityDelta)}</td>
                            <td>{formatDelta(row.sensitivityDelta)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              {comparisonData.methodologyNotes.length > 0 ? (
                <section className="sci-panel">
                  <div className="sci-panel__header">
                    <div>
                      <h2 className="sci-panel__title">Methodology &amp; Interpretation Notes</h2>
                      <p className="sci-panel__subtitle">
                        Disclosed constraints from Core scientific comparison
                      </p>
                    </div>
                  </div>
                  <ul>
                    {comparisonData.methodologyNotes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
