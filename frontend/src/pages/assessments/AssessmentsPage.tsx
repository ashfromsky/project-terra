import { useMemo, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  parseReadinessReport,
  parseScientificAssessmentResult,
  useAssessmentDetailQuery,
  useAssessmentMethodsQuery,
  useAssessmentReadinessQuery,
  useAssessmentsQuery,
  useCreateAssessmentMutation,
  useExecuteAssessmentMutation,
  type AssessmentReadinessRequest,
  type ParsedResilienceDimension,
} from '../../shared/api/assessments'
import { useCurrentUserQuery } from '../../shared/api/auth'
import { ApiError } from '../../shared/api/client'
import {
  useAutoProvisionMutation,
  usePreparedDatasetsQuery,
  type AutoProvisionResponse,
} from '../../shared/api/data-sources'
import { useRegionsQuery } from '../../shared/api/regions'
import { APP_ROUTES } from '../../shared/config/routes'
import {
  buildAnomaliesChartOption,
  buildTimeSeriesChartOption,
} from '../../shared/lib/scientific-charts'
import { AuthActionBanner } from '../../shared/ui/auth-action-banner'
import { Button } from '../../shared/ui/button'
import { Chart } from '../../shared/ui/chart'
import { ReadinessDiagnosticsPanel } from '../../shared/ui/readiness-diagnostics'
import { StatusBadge, type StatusBadgeTone } from '../../shared/ui/status-badge'

type WorkspaceTab = 'results' | 'methods'

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
    case 'unavailable':
      return 'error'
    default:
      return 'neutral'
  }
}

function formatNumber(val: number | null, digits = 3): string {
  if (val === null || !Number.isFinite(val)) return '—'
  return val.toFixed(digits)
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toISOString().slice(0, 10)
}

function shiftIsoDateDays(dateStr: string, deltaDays: number): string {
  const parsed = new Date(`${dateStr}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return dateStr
  parsed.setUTCDate(parsed.getUTCDate() + deltaDays)
  return parsed.toISOString().slice(0, 10)
}

function renderDimensionCard(dim: ParsedResilienceDimension | null, label: string) {
  if (!dim) {
    return (
      <article key={label} className="sci-dim-card">
        <div className="sci-dim-card__head">
          <span className="sci-dim-card__name">{label}</span>
          <StatusBadge tone="neutral">unavailable</StatusBadge>
        </div>
        <p className="sci-dim-card__value">—</p>
        <p className="sci-dim-card__note">Dimension payload not present in assessment result.</p>
      </article>
    )
  }

  return (
    <article key={dim.dimension || label} className="sci-dim-card">
      <div className="sci-dim-card__head">
        <span className="sci-dim-card__name">{dim.dimension || label}</span>
        <StatusBadge tone={statusTone(dim.status)}>{dim.status}</StatusBadge>
      </div>
      <p className="sci-dim-card__value">
        {dim.available && dim.value !== null ? formatNumber(dim.value, 4) : 'Unavailable'}
        {dim.unit ? <span className="sci-dim-card__unit">{dim.unit}</span> : null}
      </p>
      {dim.formula ? <p className="sci-dim-card__formula">{dim.formula}</p> : null}
      {dim.interpretation ? <p className="sci-dim-card__note">{dim.interpretation}</p> : null}
      {dim.eventValues.length > 0 ? (
        <div className="provenance-table-wrapper">
          <table className="provenance-table" aria-label={`${dim.dimension} event breakdown`}>
            <thead>
              <tr>
                <th scope="col">Event start</th>
                <th scope="col">Peak neg. z</th>
                <th scope="col">Resistance</th>
              </tr>
            </thead>
            <tbody>
              {dim.eventValues.map((ev) => (
                <tr key={`${ev.eventStart}-${ev.peakNegativeZscore}`}>
                  <td>{formatDate(ev.eventStart)}</td>
                  <td>{formatNumber(ev.peakNegativeZscore, 2)}</td>
                  <td>{formatNumber(ev.resistance, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {dim.limitations.length > 0 ? (
        <p className="sci-dim-card__note">Limitation: {dim.limitations.join(' ')}</p>
      ) : null}
    </article>
  )
}

function PreparedDatasetPickerField(props: {
  enabled: boolean
  selectedDatasetIds: string[]
  onToggle: (datasetId: string) => void
}) {
  const datasetsQuery = usePreparedDatasetsQuery(props.enabled)
  const datasets = datasetsQuery.data ?? []

  return (
    <div className="sci-field">
      <div className="sci-run-item__top">
        <span className="sci-label">Prepared GHS datasets</span>
        <Link to={APP_ROUTES.dataSources} className="sci-dim-card__note">
          Ingest new data
        </Link>
      </div>
      {datasetsQuery.isPending ? (
        <p className="sci-dim-card__note">Loading prepared GHS datasets…</p>
      ) : datasetsQuery.isError ? (
        <p className="sci-dim-card__note">
          GHS inventory unreachable right now (manual IDs below still work if offline).
        </p>
      ) : datasets.length === 0 ? (
        <p className="sci-dim-card__note">
          No GHS datasets ingested yet. Use Data Sources to ingest real NASA observations.
        </p>
      ) : (
        <div className="sci-dataset-picker" role="group" aria-label="Prepared GHS datasets">
          {datasets.map((ds) => {
            const checked = props.selectedDatasetIds.includes(ds.datasetId)
            return (
              <label
                key={ds.datasetId}
                className={`sci-dataset-option ${checked ? 'sci-dataset-option--selected' : ''}`.trim()}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => props.onToggle(ds.datasetId)}
                />
                <span>
                  <strong>
                    {ds.provider} · {ds.product}
                  </strong>
                  <div className="sci-run-item__meta">
                    {(ds.variables ?? []).join(', ') || 'variables'} · {ds.observationCount} obs ·{' '}
                    {ds.temporalStart ? ds.temporalStart.slice(0, 10) : 'n/a'} →{' '}
                    {ds.temporalEnd ? ds.temporalEnd.slice(0, 10) : 'n/a'} ·{' '}
                    {ds.datasetId.slice(0, 8)}
                  </div>
                </span>
              </label>
            )
          })}
        </div>
      )}
    </div>
  )
}

function AssessmentVisualizationsSection(props: {
  parsedResult: NonNullable<ReturnType<typeof parseScientificAssessmentResult>>
}) {
  const { parsedResult } = props
  const [selectedVar, setSelectedVar] = useState('')

  const availableVars = useMemo(() => {
    const names = new Set<string>()
    parsedResult.temporalSeries.forEach((s) => names.add(s.variableName))
    parsedResult.anomalies.forEach((a) => names.add(a.variableName))
    return Array.from(names)
  }, [parsedResult.anomalies, parsedResult.temporalSeries])

  const activeVar = useMemo(() => {
    if (selectedVar && availableVars.includes(selectedVar)) return selectedVar
    return availableVars[0] ?? ''
  }, [availableVars, selectedVar])

  const activeSeries = parsedResult.temporalSeries.find((s) => s.variableName === activeVar) ?? null
  const activeAnomaly = parsedResult.anomalies.find((a) => a.variableName === activeVar) ?? null
  const activeBaseline = parsedResult.baselines.find((b) => b.variableName === activeVar) ?? null

  const seriesOption = useMemo(() => {
    if (!activeSeries || activeSeries.timestamps.length === 0) return null
    return buildTimeSeriesChartOption({
      title: `Temporal Series · ${activeSeries.variableName}`,
      variableName: activeSeries.variableName,
      units: activeSeries.units || undefined,
      timestamps: activeSeries.timestamps,
      values: activeSeries.values,
    })
  }, [activeSeries])

  const anomalyOption = useMemo(() => {
    if (!activeAnomaly || activeAnomaly.timestamps.length === 0) return null
    return buildAnomaliesChartOption({
      variableName: activeAnomaly.variableName,
      timestamps: activeAnomaly.timestamps,
      standardZscores: activeAnomaly.standardZscores,
      robustZscores: activeAnomaly.robustZscores,
    })
  }, [activeAnomaly])

  if (
    !seriesOption &&
    !anomalyOption &&
    !activeBaseline &&
    parsedResult.crossVariable.length === 0
  ) {
    return (
      <div className="sci-banner sci-banner--neutral">
        <strong>No chartable series or baseline outputs</strong>
        <p>
          Selected datasets did not yield aligned temporal observations or cross-variable pairs for
          chart rendering. Check quality screening and stage warnings below.
        </p>
      </div>
    )
  }

  return (
    <section className="sci-main-stack" aria-label="Time series and anomaly charts">
      <div className="sci-panel__header">
        <div>
          <h3 className="sci-panel__title">Time Series &amp; Standardized Anomalies</h3>
          {activeSeries ? (
            <p className="sci-panel__subtitle">
              Cadence: {activeSeries.cadence} · Aggregation: {activeSeries.aggregationOperator}
              {activeBaseline
                ? ` · Baseline (${activeBaseline.baselineType}, ${activeBaseline.binCounts.reduce((a, b) => a + b, 0)} ref samples)`
                : ''}
            </p>
          ) : null}
        </div>
        {availableVars.length > 1 ? (
          <div className="sci-filter-bar">
            <label className="sci-label" htmlFor="assessment-chart-var">
              Variable
            </label>
            <select
              id="assessment-chart-var"
              className="sci-select"
              style={{ width: 'auto', minWidth: 150 }}
              value={activeVar}
              onChange={(e) => setSelectedVar(e.target.value)}
            >
              {availableVars.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>

      {seriesOption ? (
        <div className="sci-dim-card">
          <span className="sci-dim-card__name">AOI Temporal Trajectory · {activeVar}</span>
          <Chart option={seriesOption} className="sci-chart-box" />
        </div>
      ) : null}

      {anomalyOption ? (
        <div className="sci-dim-card">
          <div className="sci-dim-card__head">
            <span className="sci-dim-card__name">
              Standardized &amp; Robust Z-Score Anomalies · {activeVar}
            </span>
            {activeAnomaly && activeAnomaly.persistentRuns.length > 0 ? (
              <StatusBadge tone="warning">
                {activeAnomaly.persistentRuns.length} persistent anomaly runs
              </StatusBadge>
            ) : null}
          </div>
          <Chart option={anomalyOption} className="sci-chart-box" />
        </div>
      ) : null}

      {activeBaseline ? (
        <div className="sci-dim-card">
          <div className="sci-dim-card__head">
            <span className="sci-dim-card__name">
              Baseline Climatology · {activeBaseline.variableName} ({activeBaseline.baselineType})
            </span>
            <StatusBadge tone={activeBaseline.sufficient ? 'success' : 'warning'}>
              {activeBaseline.sufficient ? 'sufficient' : 'insufficient'} ·{' '}
              {activeBaseline.binCounts.reduce((a, b) => a + b, 0)} ref samples
            </StatusBadge>
          </div>
          {activeBaseline.referenceStart && activeBaseline.referenceEnd ? (
            <p className="sci-dim-card__note">
              Reference window: {formatDate(activeBaseline.referenceStart)} →{' '}
              {formatDate(activeBaseline.referenceEnd)} ({activeBaseline.seasonalGrouping})
            </p>
          ) : null}
          {activeBaseline.warnings.length > 0 ? (
            <ul className="sci-dim-card__note">
              {activeBaseline.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          {activeBaseline.bins.length > 0 ? (
            <div className="provenance-table-wrapper">
              <table className="provenance-table">
                <thead>
                  <tr>
                    <th scope="col">Bin</th>
                    <th scope="col">Samples</th>
                    <th scope="col">Mean</th>
                    <th scope="col">Median</th>
                    <th scope="col">Std</th>
                    <th scope="col">MAD</th>
                    <th scope="col">Q10–Q90</th>
                  </tr>
                </thead>
                <tbody>
                  {activeBaseline.bins.map((bin) => (
                    <tr key={`${bin.binKey}-${bin.binLabel}`}>
                      <td className="provenance-table__primary">{bin.binLabel}</td>
                      <td>{bin.sampleCount}</td>
                      <td>{formatNumber(bin.mean, 3)}</td>
                      <td>{formatNumber(bin.median, 3)}</td>
                      <td>{formatNumber(bin.std, 3)}</td>
                      <td>{formatNumber(bin.mad, 3)}</td>
                      <td>
                        {formatNumber(bin.q10, 2)} – {formatNumber(bin.q90, 2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}

      {parsedResult.crossVariable.length > 0 ? (
        <div>
          <h3 className="sci-panel__title">Cross-Variable Associations</h3>
          <div className="provenance-table-wrapper">
            <table className="provenance-table">
              <thead>
                <tr>
                  <th scope="col">Variables (X ↔ Y)</th>
                  <th scope="col">Pearson r</th>
                  <th scope="col">Spearman ρ</th>
                  <th scope="col">Lag</th>
                  <th scope="col">p-value (n)</th>
                  <th scope="col">Epistemic Caveat</th>
                </tr>
              </thead>
              <tbody>
                {parsedResult.crossVariable.map((cv) => (
                  <tr key={`${cv.xVariable}-${cv.yVariable}-${cv.lagSteps}`}>
                    <td className="provenance-table__primary">
                      {cv.xVariable} ↔ {cv.yVariable}
                    </td>
                    <td>{formatNumber(cv.pearsonR, 3)}</td>
                    <td>{formatNumber(cv.spearmanRho, 3)}</td>
                    <td>{cv.lagSteps}</td>
                    <td>
                      {formatNumber(cv.pValue, 4)} (n={cv.sampleCount})
                    </td>
                    <td style={{ whiteSpace: 'normal', minWidth: 220 }}>{cv.caveat}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  )
}

export default function AssessmentsPage() {
  const [searchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('results')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [regionId, setRegionId] = useState(() => searchParams.get('regionId') ?? '')
  const [analysisStart, setAnalysisStart] = useState('2021-01-01')
  const [analysisEnd, setAnalysisEnd] = useState('2024-12-31')
  const [baselineType, setBaselineType] = useState<'fixed_reference' | 'full_period_explicit'>(
    'fixed_reference',
  )
  const [baselineStart, setBaselineStart] = useState('2018-01-01')
  const [baselineEnd, setBaselineEnd] = useState('2020-12-31')
  const [targetCadence, setTargetCadence] = useState<'monthly' | 'daily' | 'sixteen_day'>('monthly')
  const [qaLevel, setQaLevel] = useState<'strict' | 'permissive'>('strict')
  const [minYearsRequired, setMinYearsRequired] = useState(3)
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>(() => {
    const preselected = searchParams.get('datasetId')
    return preselected ? [preselected] : []
  })
  const [ghsDatasetIdsText, setGhsDatasetIdsText] = useState('')
  const [executeNow, setExecuteNow] = useState(true)
  const [formError, setFormError] = useState<string | null>(null)
  const [provisionResult, setProvisionResult] = useState<AutoProvisionResponse | null>(null)

  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)

  const methodsQuery = useAssessmentMethodsQuery()
  const regionsQuery = useRegionsQuery(isAuthenticated)
  const preparedDatasetsQuery = usePreparedDatasetsQuery(isAuthenticated)
  const assessmentsQuery = useAssessmentsQuery(isAuthenticated)

  const activeAssessmentId = useMemo(() => {
    if (selectedId) return selectedId
    const first = assessmentsQuery.data?.[0]
    return first ? first.id : null
  }, [selectedId, assessmentsQuery.data])

  const detailQuery = useAssessmentDetailQuery(activeAssessmentId, isAuthenticated)
  const createMutation = useCreateAssessmentMutation()
  const executeMutation = useExecuteAssessmentMutation()
  const autoProvisionMutation = useAutoProvisionMutation()

  const parsedResult = useMemo(
    () => parseScientificAssessmentResult(detailQuery.data?.result),
    [detailQuery.data?.result],
  )

  const effectiveDatasetIds = useMemo(() => {
    const manualIds = ghsDatasetIdsText
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    return Array.from(new Set([...selectedDatasetIds, ...manualIds]))
  }, [ghsDatasetIdsText, selectedDatasetIds])

  const scientificRequestConfig = useMemo<Record<string, unknown>>(
    () => ({
      request_id: `ui-preview`,
      analysis_start: `${analysisStart}T00:00:00Z`,
      analysis_end: `${analysisEnd}T23:59:59Z`,
      target_cadence: targetCadence,
      qa_level: qaLevel,
      baseline:
        baselineType === 'full_period_explicit'
          ? {
              baseline_type: 'full_period_explicit',
              allow_explicit_full_period: true,
              exclude_assessment_overlap: false,
              min_years_required: minYearsRequired,
              min_samples_per_bin: Math.max(1, minYearsRequired),
            }
          : {
              baseline_type: 'fixed_reference',
              start: baselineStart ? `${baselineStart}T00:00:00Z` : undefined,
              end: baselineEnd ? `${baselineEnd}T23:59:59Z` : undefined,
              min_years_required: minYearsRequired,
              min_samples_per_bin: Math.max(1, minYearsRequired),
            },
    }),
    [
      analysisEnd,
      analysisStart,
      baselineEnd,
      baselineStart,
      baselineType,
      minYearsRequired,
      qaLevel,
      targetCadence,
    ],
  )

  const isReadinessConfigValid = Boolean(
    isAuthenticated &&
      analysisStart &&
      analysisEnd &&
      analysisStart <= analysisEnd &&
      (baselineType !== 'fixed_reference' ||
        (baselineStart && baselineEnd && baselineStart <= baselineEnd && baselineEnd < analysisStart)),
  )

  const readinessRequest = useMemo<AssessmentReadinessRequest>(
    () => ({
      regionId: regionId || null,
      requestConfig: scientificRequestConfig,
      ghsDatasetIds: effectiveDatasetIds,
      inlineDatasets: [],
    }),
    [effectiveDatasetIds, regionId, scientificRequestConfig],
  )

  const readinessQuery = useAssessmentReadinessQuery(readinessRequest, isReadinessConfigValid)
  const parsedPreRunReadiness = useMemo(
    () => parseReadinessReport(readinessQuery.data ?? provisionResult?.readiness),
    [provisionResult?.readiness, readinessQuery.data],
  )

  const syncDatesFromDatasetIds = (nextIds: string[]) => {
    const datasets = preparedDatasetsQuery.data ?? []
    const matched = datasets.filter((ds) => nextIds.includes(ds.datasetId))
    const starts = matched
      .map((ds) => ds.temporalStart?.slice(0, 10))
      .filter((d): d is string => Boolean(d && /^\d{4}-\d{2}-\d{2}$/.test(d)))
      .sort()
    const ends = matched
      .map((ds) => ds.temporalEnd?.slice(0, 10))
      .filter((d): d is string => Boolean(d && /^\d{4}-\d{2}-\d{2}$/.test(d)))
      .sort()
    if (starts.length > 0 && ends.length > 0) {
      const minStart = starts[0]
      const maxEnd = ends[ends.length - 1]
      setAnalysisStart(minStart)
      setAnalysisEnd(maxEnd)

      const startYear = Number(minStart.slice(0, 4))
      const endYear = Number(maxEnd.slice(0, 4))
      if (Number.isFinite(startYear) && Number.isFinite(endYear) && endYear - startYear >= 3) {
        const splitYear = Math.min(startYear + 2, endYear - 1)
        setBaselineStart(minStart)
        setBaselineEnd(`${splitYear}-12-31`)
        setAnalysisStart(`${splitYear + 1}-01-01`)
      } else {
        setBaselineStart('')
        setBaselineEnd('')
      }
    }
  }

  const handleAutoProvision = async () => {
    setFormError(null)
    const fallbackDatasetRegionId =
      preparedDatasetsQuery.data?.find((ds) => effectiveDatasetIds.includes(ds.datasetId))
        ?.regionId ?? null
    const resolvedRegionId = regionId || fallbackDatasetRegionId

    if (!resolvedRegionId) {
      setFormError(
        'Select a saved Region / AOI in the configuration rail before auto-provisioning datasets.',
      )
      return
    }
    if (!analysisStart || !analysisEnd || analysisStart > analysisEnd) {
      setFormError('Analysis start date must be on or before analysis end date.')
      return
    }

    try {
      const res = await autoProvisionMutation.mutateAsync({
        regionId: resolvedRegionId,
        bbox: null,
        analysisStart: `${analysisStart}T00:00:00Z`,
        analysisEnd: `${analysisEnd}T23:59:59Z`,
        targetCadence,
        baselineType: baselineType === 'fixed_reference' ? 'fixed_reference' : 'full_period_explicit',
        referenceStart:
          baselineType === 'fixed_reference' && baselineStart ? `${baselineStart}T00:00:00Z` : null,
        referenceEnd:
          baselineType === 'fixed_reference' && baselineEnd ? `${baselineEnd}T23:59:59Z` : null,
        minReferenceYears: minYearsRequired,
        qaLevel,
        existingDatasetIds: effectiveDatasetIds,
        desiredDomains: ['climate', 'precipitation', 'soil_moisture', 'vegetation'],
        maxGranulesPerProduct: 48,
      })
      setProvisionResult(res)
      if (!regionId && resolvedRegionId) {
        setRegionId(resolvedRegionId)
      }
      if ((res.datasetIds ?? []).length > 0) {
        setSelectedDatasetIds(Array.from(new Set(res.datasetIds)))
        setGhsDatasetIdsText('')
      }
      if (baselineType === 'fixed_reference') {
        const provStart = res.provisionStart.slice(0, 10)
        if (!baselineStart || provStart < baselineStart) {
          setBaselineStart(provStart)
        }
        const dayBeforeAnalysis = shiftIsoDateDays(analysisStart, -1)
        if (!baselineEnd || baselineEnd >= analysisStart) {
          setBaselineEnd(dayBeforeAnalysis)
        }
      }
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : String(cause)
      setFormError(msg)
    }
  }

  const handleCreateSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(null)

    const cleanTitle = title.trim()
    if (!cleanTitle) {
      setFormError('Assessment title is required.')
      return
    }

    const ghsIds = effectiveDatasetIds

    if (ghsIds.length === 0) {
      setFormError('Select or provide at least one prepared GHS dataset ID.')
      return
    }

    if (analysisStart > analysisEnd) {
      setFormError('Analysis start date must be on or before analysis end date.')
      return
    }

    if (baselineType === 'fixed_reference') {
      if (!baselineStart || !baselineEnd) {
        setFormError(
          'Fixed reference baseline requires baseline start and end dates with historical coverage, or switch baseline mode to Full period (explicit).',
        )
        return
      }
      if (baselineStart > baselineEnd) {
        setFormError('Baseline start date must be on or before baseline end date.')
        return
      }
      if (baselineEnd >= analysisStart) {
        setFormError(
          'Fixed reference baseline end date must precede analysis start date to prevent data leakage.',
        )
        return
      }
    }

    try {
      const created = await createMutation.mutateAsync({
        title: cleanTitle,
        regionId: regionId || null,
        executeNow,
        ghsDatasetIds: ghsIds,
        inlineDatasets: [],
        requestConfig: {
          ...scientificRequestConfig,
          request_id: `ui-${Date.now()}`,
        },
      })
      setSelectedId(created.id)
      setActiveTab('results')
      setTitle('')
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : String(cause)
      setFormError(msg)
    }
  }

  const handleExecute = async (assessmentId: string) => {
    setFormError(null)
    try {
      const updated = await executeMutation.mutateAsync(assessmentId)
      setSelectedId(updated.id)
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : String(cause)
      setFormError(msg)
    }
  }

  const activeSummaryStatus = detailQuery.data?.status
  const canExecuteActive = activeSummaryStatus === 'queued' || activeSummaryStatus === 'failed'

  return (
    <div className="workspace-page">
      <section className="workspace-context-bar" aria-label="Assessments context">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading">Ecosystem Resilience Assessments</h1>
          <p className="workspace-context-bar__breadcrumb">
            Assessments  /  Core Scientific API (/api/v1/assessments)  /  Separated Dimensions &amp; Provenance
          </p>
        </div>
        <div className="workspace-context-bar__actions">
          <StatusBadge tone={isAuthenticated ? 'teal' : 'neutral'}>
            {isAuthenticated
              ? `Signed in · @${currentUserQuery.data?.githubLogin ?? 'user'}`
              : 'Read-only · Method catalog public'}
          </StatusBadge>
          <Link to={APP_ROUTES.dataSources} className="terra-link-reset">
            <Button variant="secondary">Inspect Data Sources &amp; Provenance</Button>
          </Link>
        </div>
      </section>

      <div className="sci-workspace-shell">
        <aside className="sci-rail" aria-label="Assessment configuration and run history">
          <div>
            <h2 className="workspace-config-rail__title">Create &amp; Run Assessment</h2>
            <p className="workspace-config-rail__subtitle">
              Persists to Core API and executes Scientific Core P0/P1 pipeline without composite TRI pooling.
            </p>
          </div>

          {currentUserQuery.isPending ? (
            <div className="sci-banner sci-banner--neutral" aria-live="polite">
              Checking session status…
            </div>
          ) : !isAuthenticated ? (
            <AuthActionBanner
              returnTo={APP_ROUTES.assessments}
              title="Authentication required"
              description="Sign in to select prepared GHS datasets, create assessments, and run Scientific Core pipelines."
            />
          ) : (
            <form className="sci-form" onSubmit={handleCreateSubmit}>
              <div className="sci-field">
                <label className="sci-label" htmlFor="assessment-title">
                  Title
                </label>
                <input
                  id="assessment-title"
                  className="sci-input"
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Carpathian NDVI 2021–2024"
                  maxLength={255}
                />
              </div>

              <div className="sci-field">
                <label className="sci-label" htmlFor="assessment-region">
                  Region / AOI (optional)
                </label>
                <select
                  id="assessment-region"
                  className="sci-select"
                  value={regionId}
                  onChange={(e) => setRegionId(e.target.value)}
                >
                  <option value="">No persisted region linked</option>
                  {(regionsQuery.data ?? []).map((reg) => (
                    <option key={reg.id} value={reg.id}>
                      {reg.name} ({reg.role})
                    </option>
                  ))}
                </select>
              </div>

              <div className="sci-field-row">
                <div className="sci-field">
                  <label className="sci-label" htmlFor="analysis-start">
                    Analysis start
                  </label>
                  <input
                    id="analysis-start"
                    className="sci-input"
                    type="date"
                    value={analysisStart}
                    onChange={(e) => setAnalysisStart(e.target.value)}
                  />
                </div>
                <div className="sci-field">
                  <label className="sci-label" htmlFor="analysis-end">
                    Analysis end
                  </label>
                  <input
                    id="analysis-end"
                    className="sci-input"
                    type="date"
                    value={analysisEnd}
                    onChange={(e) => setAnalysisEnd(e.target.value)}
                  />
                </div>
              </div>

              <div className="sci-field">
                <label className="sci-label" htmlFor="baseline-type">
                  Baseline methodology
                </label>
                <select
                  id="baseline-type"
                  className="sci-select"
                  value={baselineType}
                  onChange={(e) =>
                    setBaselineType(
                      e.target.value as 'fixed_reference' | 'full_period_explicit',
                    )
                  }
                >
                  <option value="fixed_reference">Fixed reference (historical window)</option>
                  <option value="full_period_explicit">
                    Full period (explicit — includes assessment period)
                  </option>
                </select>
                {baselineType === 'fixed_reference' && (!baselineStart || !baselineEnd) ? (
                  <p className="sci-dim-card__note">
                    Selected datasets span fewer than 3 years; ingest historical reference data or
                    switch to Full period (explicit) to compute exploratory anomalies.
                  </p>
                ) : null}
              </div>

              {baselineType === 'fixed_reference' ? (
                <div className="sci-field-row">
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="baseline-start">
                      Baseline start
                    </label>
                    <input
                      id="baseline-start"
                      className="sci-input"
                      type="date"
                      value={baselineStart}
                      onChange={(e) => setBaselineStart(e.target.value)}
                    />
                  </div>
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="baseline-end">
                      Baseline end
                    </label>
                    <input
                      id="baseline-end"
                      className="sci-input"
                      type="date"
                      value={baselineEnd}
                      onChange={(e) => setBaselineEnd(e.target.value)}
                    />
                  </div>
                </div>
              ) : null}

              <div className="sci-field-row">
                <div className="sci-field">
                  <label className="sci-label" htmlFor="target-cadence">
                    Target cadence
                  </label>
                  <select
                    id="target-cadence"
                    className="sci-select"
                    value={targetCadence}
                    onChange={(e) =>
                      setTargetCadence(e.target.value as 'monthly' | 'daily' | 'sixteen_day')
                    }
                  >
                    <option value="monthly">Monthly</option>
                    <option value="sixteen_day">16-Day</option>
                    <option value="daily">Daily</option>
                  </select>
                </div>
                <div className="sci-field">
                  <label className="sci-label" htmlFor="qa-policy">
                    QA screening level
                  </label>
                  <select
                    id="qa-policy"
                    className="sci-select"
                    value={qaLevel}
                    onChange={(e) => setQaLevel(e.target.value as 'strict' | 'permissive')}
                  >
                    <option value="strict">Strict (high-confidence QA only)</option>
                    <option value="permissive">Permissive (retain marginal QA)</option>
                  </select>
                </div>
              </div>

              <div className="sci-field">
                <label className="sci-label" htmlFor="min-baseline-years">
                  Min baseline years
                </label>
                <input
                  id="min-baseline-years"
                  className="sci-input"
                  type="number"
                  min={1}
                  max={10}
                  value={minYearsRequired}
                  onChange={(e) =>
                    setMinYearsRequired(Math.max(1, Math.min(10, Number(e.target.value) || 1)))
                  }
                />
              </div>

              <PreparedDatasetPickerField
                enabled={isAuthenticated}
                selectedDatasetIds={selectedDatasetIds}
                onToggle={(dsId) => {
                  const next = selectedDatasetIds.includes(dsId)
                    ? selectedDatasetIds.filter((id) => id !== dsId)
                    : [...selectedDatasetIds, dsId]
                  setSelectedDatasetIds(next)
                  syncDatesFromDatasetIds(next)
                }}
              />

              <div className="sci-field">
                <label className="sci-label" htmlFor="ghs-dataset-ids">
                  Additional GHS dataset IDs (comma-separated, optional)
                </label>
                <input
                  id="ghs-dataset-ids"
                  className="sci-input"
                  type="text"
                  value={ghsDatasetIdsText}
                  onChange={(e) => setGhsDatasetIdsText(e.target.value)}
                  placeholder="Optional manual IDs"
                />
              </div>

              <label className="sci-checkbox-row">
                <input
                  type="checkbox"
                  checked={executeNow}
                  onChange={(e) => setExecuteNow(e.target.checked)}
                />
                Execute immediately on creation
              </label>

              {formError ? (
                <div className="sci-banner sci-banner--error" role="alert">
                  {formError}
                </div>
              ) : null}

              <div className="sci-btn-row">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={autoProvisionMutation.isPending}
                  onClick={() => void handleAutoProvision()}
                >
                  {autoProvisionMutation.isPending
                    ? 'Provisioning data…'
                    : 'Auto-Provision Missing Data'}
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={createMutation.isPending}
                >
                  {createMutation.isPending ? 'Submitting assessment…' : 'Create assessment'}
                </Button>
              </div>
            </form>
          )}

          <hr className="workspace-divider" />

          <div>
            <h2 className="workspace-config-rail__title">Saved Assessments</h2>
            <p className="workspace-config-rail__subtitle">
              User-owned runs from <code className="sci-code-chip">GET /api/v1/assessments</code>
            </p>
          </div>

          {!isAuthenticated ? (
            <p className="sci-dim-card__note">Sign in to load your persisted assessments.</p>
          ) : assessmentsQuery.isPending ? (
            <p className="sci-dim-card__note" aria-live="polite">
              Loading assessments…
            </p>
          ) : assessmentsQuery.isError ? (
            <div className="sci-banner sci-banner--error" role="alert">
              Failed to list assessments:{' '}
              {assessmentsQuery.error instanceof ApiError
                ? assessmentsQuery.error.message
                : String(assessmentsQuery.error)}
            </div>
          ) : (assessmentsQuery.data ?? []).length === 0 ? (
            <p className="sci-dim-card__note">
              No assessments created yet. Submit a configuration above to run or queue one.
            </p>
          ) : (
            <ul className="sci-run-list">
              {(assessmentsQuery.data ?? []).map((item) => {
                const isSelected = item.id === activeAssessmentId
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={`sci-run-item ${isSelected ? 'sci-run-item--active' : ''}`.trim()}
                      onClick={() => {
                        setSelectedId(item.id)
                        setActiveTab('results')
                      }}
                    >
                      <div className="sci-run-item__top">
                        <span className="sci-run-item__title">{item.title}</span>
                        <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
                      </div>
                      <span className="sci-run-item__meta">
                        Created {formatDate(item.createdAt)} · Updated {formatDate(item.updatedAt)}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </aside>

        <main className="sci-main-stack">
          {isAuthenticated ? (
            <>
              {!isReadinessConfigValid ? (
                <section className="sci-panel" aria-label="Pre-run readiness configuration warning">
                  <div className="sci-banner sci-banner--warning">
                    <strong>Configuration check needed for pre-run readiness</strong>
                    <span>
                      Ensure analysis dates are ordered and fixed-reference baseline end precedes
                      analysis start to avoid data leakage.
                    </span>
                  </div>
                </section>
              ) : readinessQuery.isPending && !parsedPreRunReadiness ? (
                <section className="sci-panel" aria-label="Pre-run adaptive data readiness">
                  <p className="sci-panel__subtitle" aria-live="polite">
                    Evaluating adaptive source and method readiness criteria…
                  </p>
                </section>
              ) : readinessQuery.isError ? (
                <section className="sci-panel" aria-label="Pre-run adaptive data readiness error">
                  <div className="sci-banner sci-banner--error" role="alert">
                    Failed to evaluate pre-run readiness:{' '}
                    {readinessQuery.error instanceof ApiError
                      ? readinessQuery.error.message
                      : String(readinessQuery.error)}
                  </div>
                </section>
              ) : parsedPreRunReadiness ? (
                <ReadinessDiagnosticsPanel
                  readiness={parsedPreRunReadiness}
                  mode="pre_run"
                  actionSlot={
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={autoProvisionMutation.isPending}
                      onClick={() => void handleAutoProvision()}
                    >
                      {autoProvisionMutation.isPending
                        ? 'Provisioning data…'
                        : 'Auto-Provision Missing Data'}
                    </Button>
                  }
                  onApplySuggestedWindow={(startDate, endDate) => {
                    setBaselineType('fixed_reference')
                    setBaselineStart(startDate)
                    setBaselineEnd(endDate)
                  }}
                />
              ) : null}

              {provisionResult ? (
                <section className="sci-panel" aria-label="Auto-provisioning execution summary">
                  <div className="sci-panel__header">
                    <div>
                      <h3 className="sci-panel__title">Adaptive Data Provisioning Summary</h3>
                      <p className="sci-panel__subtitle">
                        Provision window: {formatDate(provisionResult.provisionStart)} →{' '}
                        {formatDate(provisionResult.provisionEnd)}
                        {provisionResult.windowExpansionReason
                          ? ` · ${provisionResult.windowExpansionReason}`
                          : ''}
                      </p>
                    </div>
                    <StatusBadge tone="teal">
                      {(provisionResult.datasetIds ?? []).length} dataset(s) linked
                    </StatusBadge>
                  </div>
                  {(provisionResult.steps ?? []).length > 0 ? (
                    <div className="provenance-table-wrapper">
                      <table className="provenance-table">
                        <thead>
                          <tr>
                            <th scope="col">Domain</th>
                            <th scope="col">Provider &amp; Product</th>
                            <th scope="col">Status</th>
                            <th scope="col">Window</th>
                            <th scope="col">Details</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(provisionResult.steps ?? []).map((step) => (
                            <tr key={`${step.domain}-${step.provider}-${step.product}`}>
                              <td className="provenance-table__primary">{step.domain}</td>
                              <td>
                                {step.provider} · {step.product}
                              </td>
                              <td>
                                <StatusBadge
                                  tone={
                                    step.status === 'provisioned' || step.status === 'reused'
                                      ? 'success'
                                      : step.status === 'skipped'
                                        ? 'warning'
                                        : 'error'
                                  }
                                >
                                  {step.status}
                                </StatusBadge>
                              </td>
                              <td>
                                {formatDate(step.windowStart)} → {formatDate(step.windowEnd)}
                              </td>
                              <td style={{ whiteSpace: 'normal', minWidth: 240 }}>{step.detail}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </section>
              ) : null}
            </>
          ) : null}

          <div className="sci-panel">
            <div className="sci-panel__header">
              <div className="sci-tablist" role="tablist" aria-label="Assessments workspace views">
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'results'}
                  className={`sci-tab ${activeTab === 'results' ? 'sci-tab--active' : ''}`.trim()}
                  onClick={() => setActiveTab('results')}
                >
                  Assessment Results &amp; Provenance
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'methods'}
                  className={`sci-tab ${activeTab === 'methods' ? 'sci-tab--active' : ''}`.trim()}
                  onClick={() => setActiveTab('methods')}
                >
                  Scientific Method Catalog ({methodsQuery.data?.length ?? 0})
                </button>
              </div>
              {activeTab === 'results' && activeAssessmentId && canExecuteActive ? (
                <Button
                  variant="primary"
                  disabled={executeMutation.isPending}
                  onClick={() => void handleExecute(activeAssessmentId)}
                >
                  {executeMutation.isPending ? 'Executing…' : 'Execute assessment'}
                </Button>
              ) : null}
            </div>

            {activeTab === 'methods' ? (
              <section aria-label="Scientific method catalog">
                {methodsQuery.isPending ? (
                  <p className="sci-panel__subtitle" aria-live="polite">
                    Loading method catalog from GET /api/v1/assessments/methods…
                  </p>
                ) : methodsQuery.isError ? (
                  <div className="sci-banner sci-banner--error" role="alert">
                    Unable to load scientific methods catalog:{' '}
                    {methodsQuery.error instanceof ApiError
                      ? methodsQuery.error.message
                      : String(methodsQuery.error)}
                  </div>
                ) : (
                  <div className="provenance-table-wrapper">
                    <table className="provenance-table">
                      <thead>
                        <tr>
                          <th scope="col">Method</th>
                          <th scope="col">Priority</th>
                          <th scope="col">Status</th>
                          <th scope="col">Version</th>
                          <th scope="col">Formula / Summary</th>
                          <th scope="col">Limitations &amp; Reference</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(methodsQuery.data ?? []).map((method) => (
                          <tr key={method.methodId}>
                            <td className="provenance-table__primary">
                              <div>{method.name}</div>
                              <div className="sci-run-item__meta">{method.methodId}</div>
                            </td>
                            <td>{method.priority}</td>
                            <td>
                              <StatusBadge tone={method.implemented ? 'success' : 'experimental'}>
                                {method.implemented ? 'implemented' : 'deferred / withheld'}
                              </StatusBadge>
                            </td>
                            <td>{method.version}</td>
                            <td style={{ whiteSpace: 'normal', minWidth: 220 }}>
                              {method.formulaSummary}
                            </td>
                            <td style={{ whiteSpace: 'normal', minWidth: 240 }}>
                              {method.limitations.join(' ')} ({method.reference})
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            ) : !isAuthenticated ? (
              <div className="sci-banner sci-banner--neutral">
                <strong>Sign in to inspect or run assessments</strong>
                <p>
                  Persisted assessments and quantitative Scientific Core outputs are scoped to
                  authenticated owners. You can still inspect all implemented and withheld formulas
                  in the Scientific Method Catalog tab.
                </p>
              </div>
            ) : !activeAssessmentId ? (
              <div className="sci-banner sci-banner--neutral">
                <strong>No assessment selected</strong>
                <p>
                  Create an assessment from the left configuration rail using prepared GHS dataset
                  IDs to view separated resilience dimensions, quality screening, uncertainty, and
                  provenance.
                </p>
              </div>
            ) : detailQuery.isPending ? (
              <div className="sci-banner sci-banner--neutral" aria-live="polite">
                Loading assessment detail from Core API…
              </div>
            ) : detailQuery.isError ? (
              <div className="sci-banner sci-banner--error" role="alert">
                Error loading assessment detail:{' '}
                {detailQuery.error instanceof ApiError
                  ? detailQuery.error.message
                  : String(detailQuery.error)}
              </div>
            ) : (
              (() => {
                const detail = detailQuery.data
                return (
                  <div className="sci-main-stack">
                    <div className="sci-panel__header">
                      <div>
                        <h2 className="sci-panel__title">{detail.title}</h2>
                        <p className="sci-panel__subtitle">
                          ID <code className="sci-code-chip">{detail.id}</code> · Created{' '}
                          {formatDate(detail.createdAt)} · Completed {formatDate(detail.completedAt)}
                        </p>
                      </div>
                      <div className="sci-btn-row">
                        <StatusBadge tone={statusTone(detail.status)}>{detail.status}</StatusBadge>
                        {parsedResult ? (
                          <>
                            <Link
                              to={`${APP_ROUTES.comparativeAnalysis}?primaryId=${encodeURIComponent(detail.id)}`}
                              className="terra-link-reset"
                            >
                              <Button variant="secondary">Compare</Button>
                            </Link>
                            <Link
                              to={`${APP_ROUTES.reports}?assessmentId=${encodeURIComponent(detail.id)}`}
                              className="terra-link-reset"
                            >
                              <Button variant="secondary">Report &amp; Export</Button>
                            </Link>
                          </>
                        ) : null}
                      </div>
                    </div>

                    {detail.status === 'queued' ? (
                      <div className="sci-banner sci-banner--warning">
                        Assessment is queued and has not executed yet. Click &ldquo;Execute
                        assessment&rdquo; to run Scientific Core synchronously in Core.
                      </div>
                    ) : null}

                    {detail.status === 'running' ? (
                      <div className="sci-banner sci-banner--teal" aria-live="polite">
                        Assessment is currently running; polling Core API for completion…
                      </div>
                    ) : null}

                    {detail.status === 'failed' || detail.errorMessage ? (
                      <div className="sci-banner sci-banner--error" role="alert">
                        <strong>Execution error</strong>
                        <span>{detail.errorMessage ?? 'Assessment execution failed.'}</span>
                      </div>
                    ) : null}

                    {(detail.status === 'insufficient_data' ||
                      detail.status === 'completed_partial') && (
                      <div
                        className={`sci-banner ${
                          detail.status === 'insufficient_data'
                            ? 'sci-banner--error'
                            : 'sci-banner--warning'
                        }`}
                      >
                        <strong>
                          {detail.status === 'insufficient_data'
                            ? 'Scientific Data Requirements Not Met'
                            : 'Partial Assessment Completion'}
                        </strong>
                        <span>
                          {parsedResult?.readiness?.summary ||
                            parsedResult?.errors[0] ||
                            parsedResult?.warnings[0] ||
                            'One or more scientific readiness criteria did not pass; review the per-criterion and metric diagnostics below.'}
                        </span>
                      </div>
                    )}

                    {parsedResult ? (
                      <>
                        {parsedResult.readiness ? (
                          <ReadinessDiagnosticsPanel
                            readiness={parsedResult.readiness}
                            mode="post_run"
                          />
                        ) : null}

                        {parsedResult.warnings.length > 0 ? (
                          <div className="sci-banner sci-banner--warning">
                            <strong>Scientific warnings</strong>
                            <ul>
                              {parsedResult.warnings.map((w) => (
                                <li key={w}>{w}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}

                        <AssessmentVisualizationsSection parsedResult={parsedResult} />

                        {parsedResult.resilience.map((resBlock) => (
                          <section
                            key={`${resBlock.datasetId}-${resBlock.variableName}`}
                            className="sci-main-stack"
                            aria-label={`Resilience dimensions for ${resBlock.variableName}`}
                          >
                            <div className="sci-panel__header">
                              <h3 className="sci-panel__title">
                                Separated Resilience Dimensions · {resBlock.variableName}
                              </h3>
                              <StatusBadge tone="experimental">
                                Composite TRI: {resBlock.compositeTriStatus}
                              </StatusBadge>
                            </div>
                            {resBlock.compositeTriReason ? (
                              <p className="sci-panel__subtitle">{resBlock.compositeTriReason}</p>
                            ) : null}
                            <div className="sci-dim-grid">
                              {renderDimensionCard(resBlock.resistance, 'resistance')}
                              {renderDimensionCard(resBlock.recovery, 'recovery')}
                              {renderDimensionCard(resBlock.stability, 'stability')}
                              {renderDimensionCard(resBlock.sensitivity, 'sensitivity')}
                            </div>
                          </section>
                        ))}

                        {parsedResult.trends.length > 0 ? (
                          <section aria-label="Monotonic trend estimates">
                            <h3 className="sci-panel__title">Trends (Mann-Kendall / Sen&apos;s Slope)</h3>
                            <div className="provenance-table-wrapper">
                              <table className="provenance-table">
                                <thead>
                                  <tr>
                                    <th scope="col">Variable</th>
                                    <th scope="col">Variant</th>
                                    <th scope="col">Valid / Total</th>
                                    <th scope="col">Direction</th>
                                    <th scope="col">Sen&apos;s slope</th>
                                    <th scope="col">p-value</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {parsedResult.trends.map((tr) => (
                                    <tr key={`${tr.datasetId}-${tr.variableName}-${tr.variant}`}>
                                      <td className="provenance-table__primary">
                                        {tr.variableName}
                                      </td>
                                      <td>{tr.variant}</td>
                                      <td>
                                        {tr.validCount} / {tr.sampleCount}
                                      </td>
                                      <td>{tr.direction}</td>
                                      <td>
                                        {formatNumber(tr.sensSlope, 4)} {tr.slopeUnit}
                                      </td>
                                      <td>{formatNumber(tr.pValue, 4)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </section>
                        ) : null}

                        {parsedResult.qualityReports.length > 0 ? (
                          <section aria-label="Dataset quality reports">
                            <h3 className="sci-panel__title">Input Quality Screening</h3>
                            <div className="provenance-table-wrapper">
                              <table className="provenance-table">
                                <thead>
                                  <tr>
                                    <th scope="col">Dataset</th>
                                    <th scope="col">Variable</th>
                                    <th scope="col">Valid / Total</th>
                                    <th scope="col">Valid %</th>
                                    <th scope="col">QA Screened</th>
                                    <th scope="col">Out of Range</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {parsedResult.qualityReports.map((qr) => (
                                    <tr key={`${qr.datasetId}-${qr.variableName}`}>
                                      <td className="provenance-table__primary">{qr.datasetId}</td>
                                      <td>{qr.variableName}</td>
                                      <td>
                                        {qr.validSteps} / {qr.totalSteps}
                                      </td>
                                      <td>{formatNumber(qr.validFraction * 100, 1)}%</td>
                                      <td>{qr.qaScreenedOutCount}</td>
                                      <td>{qr.outOfRangeCount}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </section>
                        ) : null}

                        {parsedResult.uncertainty ? (
                          <section aria-label="Uncertainty and limitations">
                            <h3 className="sci-panel__title">Uncertainty &amp; Methodological Limitations</h3>
                            <div className="sci-uncertainty-grid">
                              <article className="sci-dim-card">
                                <span className="sci-dim-card__name">Data Quality Confidence</span>
                                <span className="sci-dim-card__value">
                                  {parsedResult.uncertainty.dataQualityConfidence}
                                </span>
                                <p className="sci-dim-card__note">
                                  {parsedResult.uncertainty.dataQualityRationale}
                                </p>
                              </article>
                              <article className="sci-dim-card">
                                <span className="sci-dim-card__name">Statistical Confidence</span>
                                <span className="sci-dim-card__value">
                                  {parsedResult.uncertainty.statisticalConfidence}
                                </span>
                                <p className="sci-dim-card__note">
                                  {parsedResult.uncertainty.statisticalRationale}
                                </p>
                              </article>
                              <article className="sci-dim-card">
                                <span className="sci-dim-card__name">Scientific Confidence</span>
                                <span className="sci-dim-card__value">
                                  {parsedResult.uncertainty.scientificConfidence}
                                </span>
                                <p className="sci-dim-card__note">
                                  {parsedResult.uncertainty.scientificRationale}
                                </p>
                              </article>
                            </div>
                            {parsedResult.uncertainty.methodologicalLimitations.length > 0 ? (
                              <ul className="sci-dim-card__note">
                                {parsedResult.uncertainty.methodologicalLimitations.map((lim) => (
                                  <li key={lim}>{lim}</li>
                                ))}
                              </ul>
                            ) : null}
                          </section>
                        ) : null}

                        {parsedResult.provenance ? (
                          <section aria-label="Reproducibility provenance">
                            <h3 className="sci-panel__title">Provenance &amp; Reproducibility</h3>
                            <p className="sci-panel__subtitle">
                              Input SHA-256:{' '}
                              <code className="sci-code-chip">
                                {parsedResult.provenance.inputDigestSha256}
                              </code>
                              {' · '}
                              Methods executed:{' '}
                              {parsedResult.provenance.methodsInvoked
                                .map((m) => `${m.methodId}@${m.version}`)
                                .join(', ')}
                            </p>
                            {Object.keys(detail.artifactPaths).length > 0 ? (
                              <p className="sci-dim-card__note">
                                Artifacts persisted:{' '}
                                {Object.entries(detail.artifactPaths)
                                  .map(([k, v]) => `${k}=${v}`)
                                  .join(' · ')}
                              </p>
                            ) : null}
                          </section>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                )
              })()
            )}
          </div>
        </main>
      </div>
    </div>
  )
}
