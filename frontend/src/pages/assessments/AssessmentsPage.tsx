import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import {
  parseScientificAssessmentResult,
  useAssessmentDetailQuery,
  useAssessmentMethodsQuery,
  useAssessmentsQuery,
  useCreateAssessmentMutation,
  useExecuteAssessmentMutation,
  type ParsedResilienceDimension,
} from '../../shared/api/assessments'
import { buildGitHubLoginUrl, useCurrentUserQuery } from '../../shared/api/auth'
import { ApiError } from '../../shared/api/client'
import { useRegionsQuery } from '../../shared/api/regions'
import { APP_ROUTES } from '../../shared/config/routes'
import { Button } from '../../shared/ui/button'
import { StatusBadge, type StatusBadgeTone } from '../../shared/ui/status-badge'
import { buildSampleMod13InlineDataset } from './sample-inline-fixture'

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

export default function AssessmentsPage() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('results')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // Creation form state
  const [title, setTitle] = useState('')
  const [regionId, setRegionId] = useState('')
  const [analysisStart, setAnalysisStart] = useState('2021-01-01')
  const [analysisEnd, setAnalysisEnd] = useState('2024-12-31')
  const [baselineStart, setBaselineStart] = useState('2018-01-01')
  const [baselineEnd, setBaselineEnd] = useState('2020-12-31')
  const [ghsDatasetIdsText, setGhsDatasetIdsText] = useState('')
  const [inlineJsonText, setInlineJsonText] = useState('')
  const [executeNow, setExecuteNow] = useState(true)
  const [formError, setFormError] = useState<string | null>(null)
  const [usingFixtureHelper, setUsingFixtureHelper] = useState(false)

  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)

  const methodsQuery = useAssessmentMethodsQuery()
  const regionsQuery = useRegionsQuery(isAuthenticated)
  const assessmentsQuery = useAssessmentsQuery(isAuthenticated)

  const activeAssessmentId = useMemo(() => {
    if (selectedId) return selectedId
    const first = assessmentsQuery.data?.[0]
    return first ? first.id : null
  }, [selectedId, assessmentsQuery.data])

  const detailQuery = useAssessmentDetailQuery(activeAssessmentId, isAuthenticated)
  const createMutation = useCreateAssessmentMutation()
  const executeMutation = useExecuteAssessmentMutation()

  const parsedResult = useMemo(
    () => parseScientificAssessmentResult(detailQuery.data?.result),
    [detailQuery.data?.result],
  )

  const handleLoadSampleFixture = () => {
    setInlineJsonText(JSON.stringify(buildSampleMod13InlineDataset(), null, 2))
    if (!title.trim()) {
      setTitle('MODIS NDVI Verification Assessment')
    }
    setUsingFixtureHelper(true)
    setFormError(null)
  }

  const handleCreateSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(null)

    const cleanTitle = title.trim()
    if (!cleanTitle) {
      setFormError('Assessment title is required.')
      return
    }

    const ghsIds = ghsDatasetIdsText
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)

    let inlineDatasets: Record<string, unknown>[] = []
    if (inlineJsonText.trim().length > 0) {
      try {
        const parsed = JSON.parse(inlineJsonText) as unknown
        if (!Array.isArray(parsed)) {
          setFormError('Inline datasets JSON must be an array of dataset objects.')
          return
        }
        inlineDatasets = parsed as Record<string, unknown>[]
      } catch (cause) {
        setFormError(`Invalid inline datasets JSON: ${String(cause)}`)
        return
      }
    }

    if (ghsIds.length === 0 && inlineDatasets.length === 0) {
      setFormError('Supply at least one GHS dataset ID or an inline dataset JSON array.')
      return
    }

    try {
      const created = await createMutation.mutateAsync({
        title: cleanTitle,
        regionId: regionId || null,
        executeNow,
        ghsDatasetIds: ghsIds,
        inlineDatasets,
        requestConfig: {
          request_id: `ui-${Date.now()}`,
          analysis_start: `${analysisStart}T00:00:00Z`,
          analysis_end: `${analysisEnd}T23:59:59Z`,
          target_cadence: 'monthly',
          baseline: {
            baseline_type: 'fixed_reference',
            start: `${baselineStart}T00:00:00Z`,
            end: `${baselineEnd}T23:59:59Z`,
            min_years_required: 3,
            min_samples_per_bin: 3,
          },
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
            <div className="sci-banner sci-banner--warning">
              <p>
                Authentication is required to create, list, or execute persisted assessments (
                <code className="sci-code-chip">401 Unauthorized</code> otherwise).
              </p>
              <a href={buildGitHubLoginUrl(APP_ROUTES.assessments)} className="terra-link-reset">
                <Button variant="primary">Sign in with GitHub</Button>
              </a>
            </div>
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

              <div className="sci-field">
                <label className="sci-label" htmlFor="ghs-dataset-ids">
                  GHS dataset IDs (comma-separated, optional)
                </label>
                <input
                  id="ghs-dataset-ids"
                  className="sci-input"
                  type="text"
                  value={ghsDatasetIdsText}
                  onChange={(e) => setGhsDatasetIdsText(e.target.value)}
                  placeholder="Requires running GHS service"
                />
              </div>

              <div className="sci-field">
                <label className="sci-label" htmlFor="inline-datasets-json">
                  Inline datasets JSON array (optional)
                </label>
                <textarea
                  id="inline-datasets-json"
                  className="sci-textarea"
                  value={inlineJsonText}
                  onChange={(e) => {
                    setInlineJsonText(e.target.value)
                    setUsingFixtureHelper(false)
                  }}
                  placeholder='[{"dataset_id": "...", ...}]'
                />
                <Button type="button" variant="secondary" onClick={handleLoadSampleFixture}>
                  Load sample MODIS test input (user fixture)
                </Button>
                {usingFixtureHelper ? (
                  <p className="sci-dim-card__note">
                    Loaded user-editable synthetic MODIS fixture into the input box for testing
                    Core execution when GHS is offline.
                  </p>
                ) : null}
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

              <Button
                type="submit"
                variant="primary"
                disabled={createMutation.isPending}
              >
                {createMutation.isPending ? 'Submitting assessment…' : 'Create assessment'}
              </Button>
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
                  Create an assessment from the left configuration rail using either GHS dataset IDs
                  or inline JSON dataset series to view separated resilience dimensions, quality
                  screening, uncertainty, and provenance.
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
                      <StatusBadge tone={statusTone(detail.status)}>{detail.status}</StatusBadge>
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
                      <div className="sci-banner sci-banner--warning">
                        <strong>
                          {detail.status === 'insufficient_data'
                            ? 'Insufficient Data'
                            : 'Partial Completion'}
                        </strong>
                        <span>
                          One or more variables or pipeline stages did not meet baseline/QA sample
                          requirements. Review quality reports and warnings below.
                        </span>
                      </div>
                    )}

                    {parsedResult ? (
                      <>
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
