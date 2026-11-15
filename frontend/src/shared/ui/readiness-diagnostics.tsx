import type { ReactNode } from 'react'
import type { ParsedReadinessReport } from '../api/assessments'
import { Button } from './button'
import { StatusBadge, type StatusBadgeTone } from './status-badge'

function overallStatusTone(status: string): StatusBadgeTone {
  switch (status) {
    case 'ready':
      return 'success'
    case 'partial':
      return 'warning'
    case 'insufficient':
      return 'error'
    default:
      return 'neutral'
  }
}

function overallStatusLabel(status: string): string {
  switch (status) {
    case 'ready':
      return 'Ready'
    case 'partial':
      return 'Partial'
    case 'insufficient':
      return 'Insufficient'
    default:
      return status
  }
}

function criterionTone(status: string): StatusBadgeTone {
  switch (status) {
    case 'passed':
      return 'success'
    case 'warning':
      return 'warning'
    case 'failed':
      return 'error'
    default:
      return 'neutral'
  }
}

function criterionLabel(status: string): string {
  switch (status) {
    case 'passed':
      return 'Passed'
    case 'warning':
      return 'Warning'
    case 'failed':
      return 'Failed'
    default:
      return status
  }
}

function metricTone(status: string): StatusBadgeTone {
  switch (status) {
    case 'available':
      return 'success'
    case 'degraded':
      return 'warning'
    case 'unavailable':
      return 'error'
    case 'deferred':
      return 'experimental'
    default:
      return 'neutral'
  }
}

function metricLabel(status: string): string {
  switch (status) {
    case 'available':
      return 'Available'
    case 'degraded':
      return 'Degraded'
    case 'unavailable':
      return 'Unavailable'
    case 'deferred':
      return 'Deferred'
    default:
      return status
  }
}

function formatDateIso(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.slice(0, 10)
}

export interface ReadinessDiagnosticsPanelProps {
  readiness: ParsedReadinessReport
  mode: 'pre_run' | 'post_run'
  title?: string
  actionSlot?: ReactNode
  onApplySuggestedWindow?: (startDate: string, endDate: string) => void
}

export function ReadinessDiagnosticsPanel({
  readiness,
  mode,
  title,
  actionSlot,
  onApplySuggestedWindow,
}: ReadinessDiagnosticsPanelProps) {
  const heading =
    title ??
    (mode === 'pre_run'
      ? 'Pre-Run Adaptive Data Readiness'
      : 'Data Readiness & Metric Limitation Diagnostics')

  const hasSuggestedWindow = Boolean(readiness.suggestedWindowStart && readiness.suggestedWindowEnd)

  return (
    <section className="sci-panel" aria-label={heading}>
      <div className="sci-panel__header">
        <div>
          <h3 className="sci-panel__title">{heading}</h3>
          <p className="sci-panel__subtitle">
            {readiness.summary || 'Adaptive readiness profile evaluated against source and method thresholds.'}{' '}
            · Spec <code className="sci-code-chip">v{readiness.specVersion || '1.0.0'}</code>
          </p>
        </div>
        <div className="sci-btn-row">
          <StatusBadge tone={overallStatusTone(readiness.overallStatus)}>
            {overallStatusLabel(readiness.overallStatus)}
          </StatusBadge>
          {actionSlot}
        </div>
      </div>

      {hasSuggestedWindow ? (
        <div className="sci-banner sci-banner--teal">
          <div className="sci-panel__header" style={{ width: '100%', alignItems: 'center' }}>
            <span>
              Recommended historical window:{' '}
              <strong>
                {formatDateIso(readiness.suggestedWindowStart)} →{' '}
                {formatDateIso(readiness.suggestedWindowEnd)}
              </strong>
            </span>
            {mode === 'pre_run' && onApplySuggestedWindow ? (
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  onApplySuggestedWindow(
                    formatDateIso(readiness.suggestedWindowStart),
                    formatDateIso(readiness.suggestedWindowEnd),
                  )
                }
              >
                Apply Suggested Baseline Window
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {readiness.datasets.length > 0 ? (
        <div>
          <h4 className="sci-label" style={{ marginBottom: 6 }}>
            Dataset Coverage &amp; Adaptive Threshold Profiles
          </h4>
          <div className="provenance-table-wrapper">
            <table className="provenance-table">
              <thead>
                <tr>
                  <th scope="col">Source &amp; Product</th>
                  <th scope="col">Variables</th>
                  <th scope="col">Observed Window</th>
                  <th scope="col">Valid / QA Steps</th>
                  <th scope="col">QA Layers</th>
                  <th scope="col">Profile Status</th>
                </tr>
              </thead>
              <tbody>
                {readiness.datasets.map((ds) => (
                  <tr key={ds.datasetId}>
                    <td className="provenance-table__primary">
                      <div>
                        {ds.sourceId} · {ds.product}
                      </div>
                      <div className="sci-run-item__meta">{ds.datasetId}</div>
                    </td>
                    <td>{ds.variables.join(', ') || '—'}</td>
                    <td>
                      {formatDateIso(ds.observationStart)} → {formatDateIso(ds.observationEnd)} (
                      {ds.spanYears.toFixed(2)} yr)
                    </td>
                    <td>
                      {ds.validQaCount} / {ds.rawStepCount} ({(ds.validFraction * 100).toFixed(1)}%)
                    </td>
                    <td>{ds.qaLayersPresent.join(', ') || 'None'}</td>
                    <td>
                      <StatusBadge tone={overallStatusTone(ds.status)}>
                        {overallStatusLabel(ds.status)}
                      </StatusBadge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {readiness.criteria.length > 0 ? (
        <div>
          <h4 className="sci-label" style={{ marginBottom: 6 }}>
            Minimum Required Criteria vs. Actual Characteristics
          </h4>
          <div className="provenance-table-wrapper">
            <table className="provenance-table">
              <thead>
                <tr>
                  <th scope="col">Criterion &amp; Scope</th>
                  <th scope="col">Minimum Required</th>
                  <th scope="col">Actual Observed</th>
                  <th scope="col">Status</th>
                  <th scope="col">Missing Gap &amp; Remediation</th>
                </tr>
              </thead>
              <tbody>
                {readiness.criteria.map((cr) => (
                  <tr key={cr.criterionId}>
                    <td className="provenance-table__primary" style={{ whiteSpace: 'normal', minWidth: 180 }}>
                      <div>{cr.title}</div>
                      <div className="sci-run-item__meta">
                        {cr.stageOrMetric}
                        {cr.variableName ? ` · ${cr.variableName}` : ''}
                        {cr.datasetId ? ` · ${cr.datasetId.slice(0, 8)}` : ''}
                      </div>
                    </td>
                    <td style={{ whiteSpace: 'normal', minWidth: 150 }}>{cr.requiredSummary}</td>
                    <td style={{ whiteSpace: 'normal', minWidth: 150 }}>{cr.actualSummary}</td>
                    <td>
                      <StatusBadge tone={criterionTone(cr.status)}>
                        {criterionLabel(cr.status)}
                      </StatusBadge>
                    </td>
                    <td style={{ whiteSpace: 'normal', minWidth: 260 }}>
                      {cr.missingGap ? <div>{cr.missingGap}</div> : null}
                      {cr.remediation ? (
                        <div className="sci-run-item__meta">Fix: {cr.remediation}</div>
                      ) : null}
                      {!cr.missingGap && !cr.remediation ? (
                        <span className="sci-run-item__meta">{cr.scientificRationale}</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {readiness.metrics.length > 0 ? (
        <div>
          <h4 className="sci-label" style={{ marginBottom: 6 }}>
            Assessment Metrics &amp; Pipeline Stage Availability
          </h4>
          <div className="provenance-table-wrapper">
            <table className="provenance-table">
              <thead>
                <tr>
                  <th scope="col">Metric / Stage</th>
                  <th scope="col">Priority &amp; Role</th>
                  <th scope="col">Availability</th>
                  <th scope="col">Diagnostics &amp; Remediation</th>
                </tr>
              </thead>
              <tbody>
                {readiness.metrics.map((metric) => (
                  <tr key={metric.metricId}>
                    <td className="provenance-table__primary">
                      <div>{metric.label}</div>
                      <div className="sci-run-item__meta">{metric.metricId}</div>
                    </td>
                    <td>
                      {metric.priority} · {metric.required ? 'Required' : 'Optional'}
                    </td>
                    <td>
                      <StatusBadge tone={metricTone(metric.status)}>
                        {metricLabel(metric.status)}
                      </StatusBadge>
                    </td>
                    <td style={{ whiteSpace: 'normal', minWidth: 260 }}>
                      <div>{metric.reason}</div>
                      {metric.remediation ? (
                        <div className="sci-run-item__meta">Fix: {metric.remediation}</div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {readiness.recommendedActions.length > 0 ? (
        <div className="sci-banner sci-banner--neutral">
          <div>
            <strong>Recommended actions</strong>
            <ul>
              {readiness.recommendedActions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </section>
  )
}
