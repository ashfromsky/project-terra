import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  parseScientificAssessmentResult,
  useAssessmentDetailQuery,
  useAssessmentsQuery,
} from '../../shared/api/assessments'
import { buildGitHubLoginUrl, useCurrentUserQuery } from '../../shared/api/auth'
import { ApiError } from '../../shared/api/client'
import { useHealthQuery } from '../../shared/api/health'
import { useLayerCatalogQuery } from '../../shared/api/layers'
import { useSystemInfoQuery } from '../../shared/api/system'
import { APP_ROUTES } from '../../shared/config/routes'
import { Button } from '../../shared/ui/button'
import { StatusBadge, type StatusBadgeTone } from '../../shared/ui/status-badge'

function layerAvailabilityTone(status: string): StatusBadgeTone {
  switch (status) {
    case 'connected':
      return 'success'
    case 'partial':
    case 'pending':
      return 'warning'
    case 'unavailable':
      return 'error'
    default:
      return 'neutral'
  }
}

export default function DataSourcesPage() {
  const [groupFilter, setGroupFilter] = useState<string>('all')
  const [selectedAssessmentId, setSelectedAssessmentId] = useState<string | null>(null)

  const healthQuery = useHealthQuery()
  const systemInfoQuery = useSystemInfoQuery()
  const layersQuery = useLayerCatalogQuery()
  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)
  const assessmentsQuery = useAssessmentsQuery(isAuthenticated)

  const activeAssessmentId = useMemo(() => {
    if (selectedAssessmentId) return selectedAssessmentId
    return assessmentsQuery.data?.[0]?.id ?? null
  }, [selectedAssessmentId, assessmentsQuery.data])

  const detailQuery = useAssessmentDetailQuery(activeAssessmentId, isAuthenticated)
  const parsedDetail = useMemo(
    () => parseScientificAssessmentResult(detailQuery.data?.result),
    [detailQuery.data?.result],
  )

  const layers = useMemo(() => layersQuery.data ?? [], [layersQuery.data])
  const availableGroups = useMemo(
    () => ['all', ...Array.from(new Set(layers.map((layer) => layer.groupId)))],
    [layers],
  )
  const filteredLayers = useMemo(
    () =>
      groupFilter === 'all' ? layers : layers.filter((layer) => layer.groupId === groupFilter),
    [layers, groupFilter],
  )

  return (
    <div className="workspace-page">
      <section className="workspace-context-bar" aria-label="Data sources context">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading">Data provenance &amp; layer availability</h1>
          <p className="workspace-context-bar__breadcrumb">
            Data Sources  /  Core Layer Catalog (/api/v1/layers)  /  Assessment Provenance
          </p>
        </div>
        <div className="workspace-context-bar__actions">
          <StatusBadge tone={healthQuery.isError ? 'error' : 'teal'}>
            {healthQuery.isPending
              ? 'Checking Core API…'
              : healthQuery.isError
                ? 'Core API offline'
                : `Core API ${healthQuery.data.status}`}
          </StatusBadge>
          <Link to={APP_ROUTES.assessments} className="terra-link-reset">
            <Button variant="primary">Scientific Assessments</Button>
          </Link>
        </div>
      </section>

      <div className="workspace-data-sources-shell">
        <section className="sci-panel" aria-labelledby="service-boundary-heading">
          <div className="sci-panel__header">
            <div>
              <h2 id="service-boundary-heading" className="sci-panel__title">
                Provider Availability vs. Data Ingestion Boundary
              </h2>
              <p className="sci-panel__subtitle">
                Separates visualization metadata exposed by Core from isolated GHS ingestion and
                persisted assessment quality outputs.
              </p>
            </div>
            {systemInfoQuery.data ? (
              <StatusBadge tone="neutral">
                {systemInfoQuery.data.service} v{systemInfoQuery.data.version} ·{' '}
                {systemInfoQuery.data.environment}
              </StatusBadge>
            ) : null}
          </div>

          <div className="sci-dim-grid">
            <article className="sci-dim-card">
              <div className="sci-dim-card__head">
                <span className="sci-dim-card__name">Core API · Layer Catalog</span>
                <StatusBadge tone={layersQuery.isError ? 'error' : 'success'}>
                  {layersQuery.isPending
                    ? 'loading'
                    : layersQuery.isError
                      ? 'unreachable'
                      : `${layers.length} cataloged`}
                </StatusBadge>
              </div>
              <p className="sci-dim-card__note">
                Accessible via <code className="sci-code-chip">GET /api/v1/layers</code>. Reports
                map tile endpoints (such as contextual NASA GIBS imagery), native metadata, QA
                policies, and synthetic/experimental flags. Tile imagery is visualization-only and
                is never used for quantitative measurements.
              </p>
            </article>

            <article className="sci-dim-card">
              <div className="sci-dim-card__head">
                <span className="sci-dim-card__name">
                  GHS · Discovery, Jobs &amp; Raw Dataset Inventory
                </span>
                <StatusBadge tone="warning">Unavailable in Core API (ADR-0002)</StatusBadge>
              </div>
              <p className="sci-dim-card__note">
                Provider probes, granule discovery, async ingestion jobs, and harmonized dataset
                lists (<code className="sci-code-chip">/providers</code>,{' '}
                <code className="sci-code-chip">/discover</code>,{' '}
                <code className="sci-code-chip">/jobs</code>,{' '}
                <code className="sci-code-chip">/datasets</code>) run in the standalone Geospatial
                Harmonization Service and are not directly exposed by Core{' '}
                <code className="sci-code-chip">/api/v1</code>. Core queries GHS server-side during
                assessment execution when <code className="sci-code-chip">ghsDatasetIds</code> are
                supplied.
              </p>
            </article>
          </div>
        </section>

        <section className="provenance-table-card" aria-labelledby="prov-heading">
          <div className="provenance-table-card__header">
            <div>
              <h2 id="prov-heading" className="provenance-table-card__title">
                Core Layer &amp; Provider Catalog
              </h2>
              <p className="provenance-table-card__subtitle">
                Live catalog metadata from Core API — catalog presence indicates metadata or map
                tile definition, not ingested quantitative time series.
              </p>
            </div>
            <div className="sci-filter-bar">
              <label className="sci-label" htmlFor="layer-group-filter">
                Group
              </label>
              <select
                id="layer-group-filter"
                className="sci-select"
                style={{ width: 'auto', minWidth: 140 }}
                value={groupFilter}
                onChange={(e) => setGroupFilter(e.target.value)}
              >
                {availableGroups.map((group) => (
                  <option key={group} value={group}>
                    {group === 'all' ? 'All groups' : group}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {layersQuery.isPending ? (
            <p className="sci-panel__subtitle" aria-live="polite">
              Loading layer catalog from GET /api/v1/layers…
            </p>
          ) : layersQuery.isError ? (
            <div className="sci-banner sci-banner--error" role="alert">
              Failed to load Core layer catalog:{' '}
              {layersQuery.error instanceof ApiError
                ? layersQuery.error.message
                : String(layersQuery.error)}
            </div>
          ) : filteredLayers.length === 0 ? (
            <div className="sci-banner sci-banner--neutral">
              No layers matched group filter &ldquo;{groupFilter}&rdquo;.
            </div>
          ) : (
            <div className="provenance-table-wrapper">
              <table className="provenance-table">
                <thead>
                  <tr>
                    <th scope="col">Layer / Variable</th>
                    <th scope="col">Product &amp; Source</th>
                    <th scope="col">Version</th>
                    <th scope="col">Resolution &amp; Cadence</th>
                    <th scope="col">QA Policy &amp; Limitations</th>
                    <th scope="col">Catalog Availability</th>
                    <th scope="col">Quantitative Ingestion</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLayers.map((layer) => (
                    <tr key={layer.id}>
                      <td className="provenance-table__primary">
                        <div>{layer.name}</div>
                        <div className="sci-run-item__meta">
                          {layer.variable} ({layer.unit})
                        </div>
                      </td>
                      <td>
                        <div>{layer.productId}</div>
                        <div className="sci-run-item__meta">{layer.dataSource}</div>
                      </td>
                      <td>{layer.productVersion}</td>
                      <td>
                        {layer.nativeSpatialResolution} · {layer.temporalResolution}
                      </td>
                      <td style={{ whiteSpace: 'normal', minWidth: 240 }}>
                        <div>{layer.qaPolicy}</div>
                        <div className="sci-run-item__meta">{layer.limitations}</div>
                      </td>
                      <td>
                        <StatusBadge tone={layerAvailabilityTone(layer.availabilityStatus)}>
                          {layer.availabilityStatus}
                        </StatusBadge>
                        {layer.isSyntheticPreview ? (
                          <div className="sci-run-item__meta">Preview overlay only</div>
                        ) : null}
                      </td>
                      <td>
                        <StatusBadge tone="neutral">
                          {layer.tileSource.isConnected
                            ? 'Visualization only · Requires GHS ID for quantitative run'
                            : 'Metadata only · Not connected'}
                        </StatusBadge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="sci-panel" aria-labelledby="real-provenance-heading">
          <div className="sci-panel__header">
            <div>
              <h2 id="real-provenance-heading" className="sci-panel__title">
                Persisted Assessment Quality &amp; Provenance Metadata
              </h2>
              <p className="sci-panel__subtitle">
                Real dataset lineage, valid-step fractions, and QA screening counts reported by
                executed Core Scientific Assessments.
              </p>
            </div>
            {isAuthenticated && (assessmentsQuery.data ?? []).length > 0 ? (
              <div className="sci-filter-bar">
                <label className="sci-label" htmlFor="provenance-assessment-select">
                  Assessment
                </label>
                <select
                  id="provenance-assessment-select"
                  className="sci-select"
                  style={{ width: 'auto', minWidth: 220 }}
                  value={activeAssessmentId ?? ''}
                  onChange={(e) => setSelectedAssessmentId(e.target.value)}
                >
                  {(assessmentsQuery.data ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title} ({item.status})
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
          </div>

          {!isAuthenticated ? (
            <div className="sci-banner sci-banner--neutral">
              <p>Sign in to inspect persisted assessment quality screening and dataset provenance.</p>
              <a href={buildGitHubLoginUrl(APP_ROUTES.dataSources)} className="terra-link-reset">
                <Button variant="secondary">Sign in with GitHub</Button>
              </a>
            </div>
          ) : assessmentsQuery.isPending || detailQuery.isPending ? (
            <p className="sci-panel__subtitle" aria-live="polite">
              Loading assessment provenance…
            </p>
          ) : assessmentsQuery.isError ? (
            <div className="sci-banner sci-banner--error" role="alert">
              Failed to load assessments:{' '}
              {assessmentsQuery.error instanceof ApiError
                ? assessmentsQuery.error.message
                : String(assessmentsQuery.error)}
            </div>
          ) : (assessmentsQuery.data ?? []).length === 0 ? (
            <div className="sci-banner sci-banner--neutral">
              No assessments exist yet. Run an assessment on the Assessments page to inspect
              dataset quality reports and lineage hashes here.
            </div>
          ) : parsedDetail ? (
            <div className="sci-main-stack">
              {parsedDetail.qualityReports.length > 0 ? (
                <div className="provenance-table-wrapper">
                  <table className="provenance-table">
                    <thead>
                      <tr>
                        <th scope="col">Dataset ID</th>
                        <th scope="col">Variable</th>
                        <th scope="col">Valid / Total Steps</th>
                        <th scope="col">Missing Steps</th>
                        <th scope="col">QA Screened Out</th>
                        <th scope="col">Out of Range</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parsedDetail.qualityReports.map((qr) => (
                        <tr key={`${qr.datasetId}-${qr.variableName}`}>
                          <td className="provenance-table__primary">{qr.datasetId}</td>
                          <td>{qr.variableName}</td>
                          <td>
                            {qr.validSteps} / {qr.totalSteps} ({(qr.validFraction * 100).toFixed(1)}
                            %)
                          </td>
                          <td>{qr.missingSteps}</td>
                          <td>{qr.qaScreenedOutCount}</td>
                          <td>{qr.outOfRangeCount}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="sci-panel__subtitle">
                  Selected assessment has no quality report entries (status:{' '}
                  {detailQuery.data?.status}).
                </p>
              )}

              {parsedDetail.provenance ? (
                <p className="sci-dim-card__note">
                  Input digest:{' '}
                  <code className="sci-code-chip">
                    {parsedDetail.provenance.inputDigestSha256}
                  </code>{' '}
                  · Config digest:{' '}
                  <code className="sci-code-chip">
                    {parsedDetail.provenance.configDigestSha256}
                  </code>
                </p>
              ) : null}
            </div>
          ) : (
            <p className="sci-panel__subtitle">
              Selected assessment has not generated scientific provenance output yet (status:{' '}
              {detailQuery.data?.status ?? 'unknown'}).
            </p>
          )}
        </section>
      </div>
    </div>
  )
}
