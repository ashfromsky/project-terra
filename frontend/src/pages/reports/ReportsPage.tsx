import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  parseScientificAssessmentResult,
  useAssessmentArtifactsQuery,
  useAssessmentDetailQuery,
  useAssessmentsQuery,
  type AssessmentDetailResponse,
  type ParsedScientificResult,
} from '../../shared/api/assessments'
import { useCurrentUserQuery } from '../../shared/api/auth'
import { buildApiUrl } from '../../shared/api/client'
import { useRegionsQuery } from '../../shared/api/regions'
import { APP_ROUTES } from '../../shared/config/routes'
import { AuthActionBanner } from '../../shared/ui/auth-action-banner'
import { Button } from '../../shared/ui/button'
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

function formatNumber(val: number | null | undefined, digits = 4): string {
  if (val === null || val === undefined || !Number.isFinite(val)) return '—'
  return val.toFixed(digits)
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  return parsed.toISOString().slice(0, 10)
}

function triggerFileDownload(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

function csvCell(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined) return ''
  const raw = String(value)
  if (raw.includes(',') || raw.includes('"') || raw.includes('\n')) {
    return `"${raw.replace(/"/g, '""')}"`
  }
  return raw
}

function buildAssessmentCsv(
  detail: AssessmentDetailResponse,
  parsed: ParsedScientificResult,
): string {
  const rows: string[] = [
    [
      'recordType',
      'assessmentId',
      'variableName',
      'timestamp',
      'value',
      'units',
      'cadence',
      'coverageFraction',
      'standardZscore',
      'robustZscore',
      'metricName',
      'metricValue',
    ].join(','),
  ]

  for (const series of parsed.temporalSeries) {
    const anomaly = parsed.anomalies.find(
      (item) =>
        item.datasetId === series.datasetId && item.variableName === series.variableName,
    )
    series.timestamps.forEach((timestamp, idx) => {
      rows.push(
        [
          'observation',
          detail.id,
          series.variableName,
          timestamp,
          series.values[idx] ?? '',
          series.units,
          series.cadence,
          series.coverageFractions[idx] ?? '',
          anomaly?.standardZscores[idx] ?? '',
          anomaly?.robustZscores[idx] ?? '',
          '',
          '',
        ]
          .map(csvCell)
          .join(','),
      )
    })
  }

  for (const trend of parsed.trends) {
    rows.push(
      [
        'trend',
        detail.id,
        trend.variableName,
        '',
        trend.sensSlope ?? '',
        trend.slopeUnit,
        trend.variant,
        '',
        '',
        '',
        `direction=${trend.direction};pValue=${trend.pValue ?? 'null'}`,
        trend.validCount,
      ]
        .map(csvCell)
        .join(','),
    )
  }

  for (const resilience of parsed.resilience) {
    const dims = [
      resilience.resistance,
      resilience.recovery,
      resilience.stability,
      resilience.sensitivity,
    ]
    for (const dim of dims) {
      if (!dim) continue
      rows.push(
        [
          'resilience',
          detail.id,
          resilience.variableName,
          '',
          dim.value ?? '',
          dim.unit,
          '',
          '',
          '',
          '',
          dim.dimension,
          dim.status,
        ]
          .map(csvCell)
          .join(','),
      )
    }
  }

  return `${rows.join('\n')}\n`
}

function buildAssessmentMarkdown(
  detail: AssessmentDetailResponse,
  parsed: ParsedScientificResult,
  regionLabel: string,
): string {
  const lines: string[] = [
    `# PROJECT TERRA Scientific Assessment Report: ${detail.title}`,
    '',
    `- **Assessment ID**: \`${detail.id}\``,
    `- **Status**: \`${detail.status}\``,
    `- **Region / AOI**: ${regionLabel}`,
    `- **Created At**: ${detail.createdAt}`,
    `- **Completed At**: ${detail.completedAt ?? '—'}`,
    `- **GHS Dataset IDs**: ${detail.ghsDatasetIds.join(', ') || 'None'}`,
    '',
    '## 1. Trend Inference',
    '',
    '| Variable | Variant | Direction | Sen Slope | p-value | Valid / Total |',
    '|---|---|---|---:|---:|---:|',
  ]

  if (parsed.trends.length === 0) {
    lines.push('| — | — | No trend diagnostics computed | — | — | — |')
  } else {
    for (const trend of parsed.trends) {
      lines.push(
        `| ${trend.variableName} | ${trend.variant} | ${trend.direction} | ${formatNumber(trend.sensSlope, 5)} ${trend.slopeUnit} | ${formatNumber(trend.pValue, 4)} | ${trend.validCount}/${trend.sampleCount} |`,
      )
    }
  }

  lines.push('', '## 2. Disaggregated Resilience Dimensions', '')
  if (parsed.resilience.length === 0) {
    lines.push('No resilience dimensions computed.')
  } else {
    for (const entry of parsed.resilience) {
      lines.push(`### ${entry.variableName}`)
      lines.push(
        `- **Resistance**: ${entry.resistance?.available ? `${formatNumber(entry.resistance.value, 4)} (${entry.resistance.status})` : entry.resistance?.status ?? 'unavailable'}`,
      )
      lines.push(
        `- **Recovery**: ${entry.recovery?.available ? `${formatNumber(entry.recovery.value, 4)} (${entry.recovery.status})` : entry.recovery?.status ?? 'unavailable'}`,
      )
      lines.push(
        `- **Stability**: ${entry.stability?.available ? `${formatNumber(entry.stability.value, 4)} (${entry.stability.status})` : entry.stability?.status ?? 'unavailable'}`,
      )
      lines.push(
        `- **Sensitivity**: ${entry.sensitivity?.available ? `${formatNumber(entry.sensitivity.value, 4)} (${entry.sensitivity.status})` : entry.sensitivity?.status ?? 'unavailable'}`,
      )
      lines.push(
        `- **Composite TRI**: \`${entry.compositeTriStatus}\` — ${entry.compositeTriReason}`,
      )
      lines.push('')
    }
  }

  lines.push('## 3. Data Quality Screening', '')
  lines.push('| Variable | Valid / Total Steps | Valid Fraction | QA Screened Out | Out-of-Range |')
  lines.push('|---|---:|---:|---:|---:|')
  for (const qr of parsed.qualityReports) {
    lines.push(
      `| ${qr.variableName} | ${qr.validSteps}/${qr.totalSteps} | ${(qr.validFraction * 100).toFixed(1)}% | ${qr.qaScreenedOutCount} | ${qr.outOfRangeCount} |`,
    )
  }

  if (parsed.uncertainty) {
    lines.push(
      '',
      '## 4. Uncertainty & Methodological Limitations',
      '',
      `- **Data Quality Confidence**: ${parsed.uncertainty.dataQualityConfidence} (${parsed.uncertainty.dataQualityRationale})`,
      `- **Statistical Confidence**: ${parsed.uncertainty.statisticalConfidence} (${parsed.uncertainty.statisticalRationale})`,
      `- **Scientific Confidence**: ${parsed.uncertainty.scientificConfidence} (${parsed.uncertainty.scientificRationale})`,
      '',
      '### Limitations',
      ...parsed.uncertainty.methodologicalLimitations.map((limitation) => `- ${limitation}`),
    )
  }

  if (parsed.provenance) {
    lines.push(
      '',
      '## 5. Reproducibility & Provenance Manifest',
      '',
      `- **Input Digest (SHA-256)**: \`${parsed.provenance.inputDigestSha256 || '—'}\``,
      parsed.provenance.configDigestSha256
        ? `- **Config Digest (SHA-256)**: \`${parsed.provenance.configDigestSha256}\``
        : `- **Provenance Trace ID**: \`${parsed.provenance.traceId || '—'}\``,
      `- **Generated At (UTC)**: ${parsed.provenance.generatedAtUtc || '—'}`,
      '',
      '### Methods Invoked',
      ...parsed.provenance.methodsInvoked.map(
        (method) => `- \`${method.methodId}\` v${method.version}: ${method.name}`,
      ),
    )
  }

  if (parsed.warnings.length > 0 || parsed.errors.length > 0) {
    lines.push('', '## 6. Runtime Warnings & Errors', '')
    for (const warning of parsed.warnings) {
      lines.push(`- WARNING: ${warning}`)
    }
    for (const err of parsed.errors) {
      lines.push(`- ERROR: ${err}`)
    }
  }

  lines.push('')
  return lines.join('\n')
}

export default function ReportsPage() {
  const [searchParams] = useSearchParams()
  const initialAssessmentId = searchParams.get('assessmentId')
  const [selectedOverrideId, setSelectedOverrideId] = useState<string | null>(
    initialAssessmentId,
  )

  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)

  const assessmentsQuery = useAssessmentsQuery(isAuthenticated)
  const regionsQuery = useRegionsQuery(isAuthenticated)

  const regionNameById = useMemo(() => {
    const map = new Map<string, string>()
    for (const region of regionsQuery.data ?? []) {
      map.set(region.id, region.name)
    }
    return map
  }, [regionsQuery.data])

  const assessments = useMemo(() => assessmentsQuery.data ?? [], [assessmentsQuery.data])

  const effectiveAssessmentId = useMemo(() => {
    if (selectedOverrideId && assessments.some((item) => item.id === selectedOverrideId)) {
      return selectedOverrideId
    }
    const completed = assessments.find(
      (item) => item.status === 'completed' || item.status === 'completed_partial',
    )
    return completed?.id ?? assessments[0]?.id ?? null
  }, [assessments, selectedOverrideId])

  const detailQuery = useAssessmentDetailQuery(effectiveAssessmentId, isAuthenticated)
  const detail = detailQuery.data ?? null
  const artifactsQuery = useAssessmentArtifactsQuery(
    effectiveAssessmentId,
    isAuthenticated && Boolean(detail),
  )
  const persistedArtifacts = artifactsQuery.data ?? []

  const parsedResult = useMemo(
    () => (detail ? parseScientificAssessmentResult(detail.result) : null),
    [detail],
  )

  const regionLabel = detail?.regionId
    ? regionNameById.get(detail.regionId) ?? detail.regionId
    : 'Ad-hoc / unlinked AOI'

  const handleExportJson = () => {
    if (!detail) return
    const payload = {
      exportedAtUtc: new Date().toISOString(),
      sourceSystem: 'PROJECT TERRA',
      regionLabel,
      assessment: detail,
    }
    triggerFileDownload(
      `terra-assessment-${detail.id.slice(0, 8)}.json`,
      JSON.stringify(payload, null, 2),
      'application/json;charset=utf-8',
    )
  }

  const handleExportCsv = () => {
    if (!detail || !parsedResult) return
    const csvText = buildAssessmentCsv(detail, parsedResult)
    triggerFileDownload(
      `terra-assessment-${detail.id.slice(0, 8)}.csv`,
      csvText,
      'text/csv;charset=utf-8',
    )
  }

  const handleExportMarkdown = () => {
    if (!detail || !parsedResult) return
    const mdText = buildAssessmentMarkdown(detail, parsedResult, regionLabel)
    triggerFileDownload(
      `terra-assessment-${detail.id.slice(0, 8)}.md`,
      mdText,
      'text/markdown;charset=utf-8',
    )
  }

  const handlePrintPdf = () => {
    window.print()
  }

  return (
    <div className="workspace-page">
      <section className="workspace-context-bar" aria-label="Scientific reports header">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading">
            Scientific Reports &amp; Reproducible Exports
          </h1>
          <p className="workspace-context-bar__breadcrumb">
            Reports / Provenance Manifests / JSON · CSV · Markdown · Printable PDF
          </p>
        </div>
        <div className="workspace-context-bar__actions">
          {detail ? (
            <StatusBadge tone={statusTone(detail.status)}>
              {detail.status.toUpperCase()} · {detail.id.slice(0, 8)}
            </StatusBadge>
          ) : (
            <StatusBadge tone="neutral">NO REPORT SELECTED</StatusBadge>
          )}
          <Button
            type="button"
            variant={detail ? 'secondary' : 'disabled'}
            disabled={!detail}
            onClick={handleExportJson}
          >
            Export JSON
          </Button>
          <Button
            type="button"
            variant={detail && parsedResult ? 'secondary' : 'disabled'}
            disabled={!detail || !parsedResult}
            onClick={handleExportCsv}
          >
            Export CSV
          </Button>
          <Button
            type="button"
            variant={detail && parsedResult ? 'secondary' : 'disabled'}
            disabled={!detail || !parsedResult}
            onClick={handleExportMarkdown}
          >
            Export Markdown
          </Button>
          <Button
            type="button"
            variant={detail ? 'primary' : 'disabled'}
            disabled={!detail}
            onClick={handlePrintPdf}
          >
            Print / PDF
          </Button>
        </div>
      </section>

      {!isAuthenticated && !currentUserQuery.isPending ? (
        <AuthActionBanner
          returnTo={APP_ROUTES.reports}
          title="Sign in to inspect and export Scientific Assessment reports"
          description="Reproducible reports are compiled directly from your persisted Core assessment payloads, SHA-256 provenance digests, and quality diagnostics."
        />
      ) : null}

      <div className="sci-workspace-shell">
        <aside className="sci-rail" aria-label="Report assessment selector">
          <section className="sci-panel">
            <div className="sci-panel__header">
              <div>
                <h2 className="sci-panel__title">Persisted Assessments</h2>
                <p className="sci-panel__subtitle">
                  Choose a saved Scientific Assessment to inspect or export
                </p>
              </div>
            </div>

            {!isAuthenticated ? (
              <p className="workspace-config-rail__note">
                Sign in to load saved assessment runs.
              </p>
            ) : assessmentsQuery.isPending ? (
              <p className="workspace-config-rail__note">Loading assessments…</p>
            ) : assessments.length === 0 ? (
              <div className="sci-banner sci-banner--neutral">
                <span>
                  No Scientific Assessments saved yet. Run an assessment first to compile a
                  reproducible report.
                </span>
              </div>
            ) : (
              <ul className="sci-run-list">
                {assessments.map((item) => {
                  const isActive = item.id === effectiveAssessmentId
                  return (
                    <li
                      key={item.id}
                      className={`sci-run-item ${isActive ? 'sci-run-item--active' : ''}`}
                      onClick={() => setSelectedOverrideId(item.id)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          setSelectedOverrideId(item.id)
                        }
                      }}
                      tabIndex={0}
                      role="button"
                      aria-pressed={isActive}
                    >
                      <div className="sci-run-item__top">
                        <span className="sci-run-item__title">{item.title}</span>
                        <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
                      </div>
                      <span className="sci-run-item__meta">
                        {formatDate(item.completedAt ?? item.createdAt)} ·{' '}
                        {item.ghsDatasetIds.length} dataset(s)
                      </span>
                    </li>
                  )
                })}
              </ul>
            )}

            <div className="sci-btn-row">
              <Link to={APP_ROUTES.assessments} className="terra-link-reset">
                <Button variant="secondary">Open Assessments</Button>
              </Link>
              {detail ? (
                <Link
                  to={`${APP_ROUTES.comparativeAnalysis}?primaryId=${encodeURIComponent(detail.id)}`}
                  className="terra-link-reset"
                >
                  <Button variant="secondary">Compare Run</Button>
                </Link>
              ) : null}
            </div>
          </section>
        </aside>

        <main className="sci-main-stack">
          {!detail ? (
            <section className="sci-panel">
              <div className="sci-panel__header">
                <div>
                  <h2 className="sci-panel__title">Reproducible Scientific Report</h2>
                  <p className="sci-panel__subtitle">
                    Select a persisted assessment from the left rail or run a new analysis in
                    Assessments.
                  </p>
                </div>
              </div>
              <div className="sci-btn-row">
                <Link to={APP_ROUTES.assessments} className="terra-link-reset">
                  <Button variant="primary">Configure Scientific Assessment</Button>
                </Link>
                <Link to={APP_ROUTES.dataSources} className="terra-link-reset">
                  <Button variant="secondary">View Prepared Datasets</Button>
                </Link>
              </div>
            </section>
          ) : (
            <>
              <section className="sci-panel">
                <div className="sci-panel__header">
                  <div>
                    <h2 className="sci-panel__title">{detail.title}</h2>
                    <p className="sci-panel__subtitle">
                      Region: {regionLabel} · Assessment ID: {detail.id}
                    </p>
                  </div>
                  <StatusBadge tone={statusTone(detail.status)}>{detail.status}</StatusBadge>
                </div>

                <div className="sci-kpi-grid">
                  <article className="sci-dim-card">
                    <div className="sci-dim-card__head">
                      <span className="sci-dim-card__name">Completed</span>
                    </div>
                    <p className="sci-dim-card__value">
                      {formatDate(detail.completedAt ?? detail.updatedAt)}
                    </p>
                    <p className="sci-dim-card__note">Created {formatDate(detail.createdAt)}</p>
                  </article>
                  <article className="sci-dim-card">
                    <div className="sci-dim-card__head">
                      <span className="sci-dim-card__name">GHS Datasets</span>
                    </div>
                    <p className="sci-dim-card__value">{detail.ghsDatasetIds.length}</p>
                    <p className="sci-dim-card__note">Harmonized dataset inputs consumed</p>
                  </article>
                  <article className="sci-dim-card">
                    <div className="sci-dim-card__head">
                      <span className="sci-dim-card__name">Scientific Confidence</span>
                    </div>
                    <p className="sci-dim-card__value">
                      {parsedResult?.uncertainty?.scientificConfidence ?? '—'}
                    </p>
                    <p className="sci-dim-card__note">
                      Quality: {parsedResult?.uncertainty?.dataQualityConfidence ?? '—'}
                    </p>
                  </article>
                </div>
              </section>

              {!parsedResult ? (
                <section className="sci-panel">
                  <div className="sci-banner sci-banner--neutral">
                    <span>
                      {detail.status === 'queued' || detail.status === 'running'
                        ? 'This assessment is still queued or running in Core Worker. Refresh or wait a moment for the final payload.'
                        : detail.errorMessage ||
                          'No structured scientific result payload stored on this assessment yet.'}
                    </span>
                  </div>
                </section>
              ) : (
                <>
                  <section className="sci-panel">
                    <div className="sci-panel__header">
                      <div>
                        <h2 className="sci-panel__title">Trend Inference Summary</h2>
                        <p className="sci-panel__subtitle">
                          Seasonal / OLS / Mann–Kendall trend slopes and statistical p-values
                        </p>
                      </div>
                    </div>
                    {parsedResult.trends.length === 0 ? (
                      <p className="workspace-config-rail__note">
                        No trend records included in this result.
                      </p>
                    ) : (
                      <div className="provenance-table-wrapper">
                        <table className="provenance-table" aria-label="Report trend summary">
                          <thead>
                            <tr>
                              <th scope="col">Variable</th>
                              <th scope="col">Variant</th>
                              <th scope="col">Direction</th>
                              <th scope="col">Sen’s Slope</th>
                              <th scope="col">p-value</th>
                              <th scope="col">Valid / Total</th>
                            </tr>
                          </thead>
                          <tbody>
                            {parsedResult.trends.map((trend) => (
                              <tr key={`${trend.datasetId}-${trend.variableName}-${trend.variant}`}>
                                <td className="provenance-table__primary">{trend.variableName}</td>
                                <td>{trend.variant}</td>
                                <td>{trend.direction}</td>
                                <td>
                                  {formatNumber(trend.sensSlope, 5)}{' '}
                                  {trend.slopeUnit ? trend.slopeUnit : ''}
                                </td>
                                <td>{formatNumber(trend.pValue, 4)}</td>
                                <td>
                                  {trend.validCount} / {trend.sampleCount}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>

                  <section className="sci-panel">
                    <div className="sci-panel__header">
                      <div>
                        <h2 className="sci-panel__title">Resilience Dimensions &amp; Quality</h2>
                        <p className="sci-panel__subtitle">
                          Disaggregated dimensions; Composite TRI remains withheld unless validated
                        </p>
                      </div>
                    </div>

                    {parsedResult.resilience.map((entry) => (
                      <div key={`${entry.datasetId}-${entry.variableName}`} className="sci-main-stack">
                        <div className="sci-btn-row">
                          <strong>{entry.variableName}</strong>
                          <StatusBadge tone="neutral">
                            Composite TRI: {entry.compositeTriStatus}
                          </StatusBadge>
                        </div>
                        <div className="sci-dim-grid">
                          {[
                            { label: 'Resistance', dim: entry.resistance },
                            { label: 'Recovery', dim: entry.recovery },
                            { label: 'Stability', dim: entry.stability },
                            { label: 'Sensitivity', dim: entry.sensitivity },
                          ].map(({ label, dim }) => (
                            <article key={label} className="sci-dim-card">
                              <div className="sci-dim-card__head">
                                <span className="sci-dim-card__name">{label}</span>
                                <StatusBadge tone={statusTone(dim?.status ?? 'unavailable')}>
                                  {dim?.status ?? 'unavailable'}
                                </StatusBadge>
                              </div>
                              <p className="sci-dim-card__value">
                                {dim?.available ? formatNumber(dim.value, 4) : 'Unavailable'}
                                {dim?.unit ? (
                                  <span className="sci-dim-card__unit">{dim.unit}</span>
                                ) : null}
                              </p>
                              {dim?.interpretation ? (
                                <p className="sci-dim-card__note">{dim.interpretation}</p>
                              ) : null}
                            </article>
                          ))}
                        </div>
                      </div>
                    ))}

                    {parsedResult.qualityReports.length > 0 ? (
                      <div className="provenance-table-wrapper">
                        <table className="provenance-table" aria-label="Report data quality table">
                          <thead>
                            <tr>
                              <th scope="col">Variable</th>
                              <th scope="col">Valid Steps</th>
                              <th scope="col">Valid Fraction</th>
                              <th scope="col">QA Screened Out</th>
                              <th scope="col">Out of Range</th>
                            </tr>
                          </thead>
                          <tbody>
                            {parsedResult.qualityReports.map((qr) => (
                              <tr key={`${qr.datasetId}-${qr.variableName}`}>
                                <td className="provenance-table__primary">{qr.variableName}</td>
                                <td>
                                  {qr.validSteps} / {qr.totalSteps}
                                </td>
                                <td>{(qr.validFraction * 100).toFixed(1)}%</td>
                                <td>{qr.qaScreenedOutCount}</td>
                                <td>{qr.outOfRangeCount}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </section>

                  <section className="sci-panel">
                    <div className="sci-panel__header">
                      <div>
                        <h2 className="sci-panel__title">
                          Uncertainty, Limitations &amp; Provenance Manifest
                        </h2>
                        <p className="sci-panel__subtitle">
                          Audit trail, cryptographic digests, and active package versions
                        </p>
                      </div>
                    </div>

                    {parsedResult.uncertainty ? (
                      <div className="sci-uncertainty-grid">
                        <article className="sci-dim-card">
                          <div className="sci-dim-card__head">
                            <span className="sci-dim-card__name">Data Quality Confidence</span>
                            <StatusBadge tone="neutral">
                              {parsedResult.uncertainty.dataQualityConfidence}
                            </StatusBadge>
                          </div>
                          <p className="sci-dim-card__note">
                            {parsedResult.uncertainty.dataQualityRationale}
                          </p>
                        </article>
                        <article className="sci-dim-card">
                          <div className="sci-dim-card__head">
                            <span className="sci-dim-card__name">Statistical Confidence</span>
                            <StatusBadge tone="neutral">
                              {parsedResult.uncertainty.statisticalConfidence}
                            </StatusBadge>
                          </div>
                          <p className="sci-dim-card__note">
                            {parsedResult.uncertainty.statisticalRationale}
                          </p>
                        </article>
                        <article className="sci-dim-card">
                          <div className="sci-dim-card__head">
                            <span className="sci-dim-card__name">Scientific Confidence</span>
                            <StatusBadge tone="neutral">
                              {parsedResult.uncertainty.scientificConfidence}
                            </StatusBadge>
                          </div>
                          <p className="sci-dim-card__note">
                            {parsedResult.uncertainty.scientificRationale}
                          </p>
                        </article>
                      </div>
                    ) : null}

                    {parsedResult.uncertainty &&
                    parsedResult.uncertainty.methodologicalLimitations.length > 0 ? (
                      <div>
                        <strong>Methodological Limitations</strong>
                        <ul>
                          {parsedResult.uncertainty.methodologicalLimitations.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {parsedResult.provenance ? (
                      <div className="sci-btn-row">
                        <span className="sci-code-chip">
                          Input SHA-256: {parsedResult.provenance.inputDigestSha256 || '—'}
                        </span>
                        {parsedResult.provenance.configDigestSha256 ? (
                          <span className="sci-code-chip">
                            Config SHA-256: {parsedResult.provenance.configDigestSha256}
                          </span>
                        ) : (
                          <span className="sci-code-chip">
                            Trace ID: {parsedResult.provenance.traceId || '—'}
                          </span>
                        )}
                        <span className="sci-code-chip">
                          Generated UTC: {parsedResult.provenance.generatedAtUtc || '—'}
                        </span>
                      </div>
                    ) : null}

                    {parsedResult.provenance &&
                    parsedResult.provenance.methodsInvoked.length > 0 ? (
                      <div className="provenance-table-wrapper">
                        <table className="provenance-table" aria-label="Invoked scientific methods">
                          <thead>
                            <tr>
                              <th scope="col">Method ID</th>
                              <th scope="col">Version</th>
                              <th scope="col">Name</th>
                            </tr>
                          </thead>
                          <tbody>
                            {parsedResult.provenance.methodsInvoked.map((method) => (
                              <tr key={`${method.methodId}-${method.version}`}>
                                <td className="provenance-table__primary">{method.methodId}</td>
                                <td>{method.version}</td>
                                <td>{method.name}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}

                    {persistedArtifacts.length > 0 ? (
                      <div className="provenance-table-wrapper">
                        <table className="provenance-table" aria-label="Persisted object storage artifacts">
                          <thead>
                            <tr>
                              <th scope="col">Artifact</th>
                              <th scope="col">Storage</th>
                              <th scope="col">Object Key</th>
                              <th scope="col">Size</th>
                              <th scope="col">Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {persistedArtifacts.map((artifact) => {
                              const href =
                                artifact.presigned && artifact.presignedUrl
                                  ? artifact.presignedUrl
                                  : buildApiUrl(artifact.downloadPath)
                              return (
                                <tr key={artifact.name}>
                                  <td className="provenance-table__primary">{artifact.name}</td>
                                  <td>
                                    {artifact.storageBackend === 's3'
                                      ? artifact.presigned
                                        ? 'R2 (presigned)'
                                        : 'R2 / S3'
                                      : 'Local store'}
                                  </td>
                                  <td>
                                    <code className="sci-code-chip">{artifact.objectKey}</code>
                                  </td>
                                  <td>{Math.max(1, Math.round(artifact.sizeBytes / 1024))} KB</td>
                                  <td>
                                    <a
                                      href={href}
                                      download={`assessment-${detail.id.slice(0, 8)}-${artifact.name}`}
                                      target={artifact.presigned ? '_blank' : undefined}
                                      rel={artifact.presigned ? 'noopener noreferrer' : undefined}
                                      className="terra-link-reset"
                                    >
                                      <Button type="button" variant="secondary">
                                        Download
                                      </Button>
                                    </a>
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </section>
                </>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
