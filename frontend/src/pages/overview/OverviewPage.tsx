import { Link } from 'react-router'
import { useAssessmentsQuery } from '../../shared/api/assessments'
import { useCurrentUserQuery } from '../../shared/api/auth'
import { usePreparedDatasetsQuery, useProvidersQuery } from '../../shared/api/data-sources'
import { useHealthQuery } from '../../shared/api/health'
import { useLayerCatalogQuery } from '../../shared/api/layers'
import { useRegionsQuery } from '../../shared/api/regions'
import { useSystemInfoQuery } from '../../shared/api/system'
import { APP_ROUTES } from '../../shared/config/routes'
import { AuthActionBanner } from '../../shared/ui/auth-action-banner'
import { Button } from '../../shared/ui/button'
import { StatusBadge, type StatusBadgeTone } from '../../shared/ui/status-badge'

function providerTone(status: string): StatusBadgeTone {
  switch (status) {
    case 'ready':
      return 'success'
    case 'credentials_missing':
    case 'degraded':
      return 'warning'
    case 'disabled':
    case 'unavailable':
      return 'error'
    default:
      return 'neutral'
  }
}

export default function OverviewPage() {
  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)

  const healthQuery = useHealthQuery()
  const systemQuery = useSystemInfoQuery()
  const providersQuery = useProvidersQuery()
  const layersQuery = useLayerCatalogQuery()
  const regionsQuery = useRegionsQuery(isAuthenticated)
  const datasetsQuery = usePreparedDatasetsQuery(isAuthenticated)
  const assessmentsQuery = useAssessmentsQuery(isAuthenticated)

  const providers = providersQuery.data ?? []
  const readyProvidersCount = providers.filter((item) => item.status === 'ready').length
  const layers = layersQuery.data ?? []
  const regions = regionsQuery.data ?? []
  const datasets = datasetsQuery.data ?? []
  const assessments = assessmentsQuery.data ?? []
  const completedAssessmentsCount = assessments.filter(
    (item) => item.status === 'completed' || item.status === 'completed_partial',
  ).length

  const apiBadgeTone: StatusBadgeTone = healthQuery.isPending
    ? 'neutral'
    : healthQuery.isError
      ? 'error'
      : 'success'
  const apiStatusLabel = healthQuery.isPending
    ? 'CORE API: CONNECTING'
    : healthQuery.isError
      ? 'CORE API: OFFLINE'
      : `CORE API: ${healthQuery.data.status.toUpperCase()}`

  return (
    <div className="workspace-page">
      <section className="workspace-context-bar" aria-label="Platform overview header">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading">
            PROJECT TERRA · Platform Overview
          </h1>
          <p className="workspace-context-bar__breadcrumb">
            Overview / Operational Readiness / End-to-End Environmental Analysis Workflow
          </p>
        </div>
        <div className="workspace-context-bar__actions">
          <StatusBadge tone={apiBadgeTone}>{apiStatusLabel}</StatusBadge>
          <Link to={APP_ROUTES.explore} className="terra-link-reset">
            <Button variant="secondary">Explore Global Map</Button>
          </Link>
          <Link to={APP_ROUTES.dataSources} className="terra-link-reset">
            <Button variant="secondary">Data Sources</Button>
          </Link>
          <Link to={APP_ROUTES.assessments} className="terra-link-reset">
            <Button variant="primary">Scientific Assessments</Button>
          </Link>
        </div>
      </section>

      {!isAuthenticated && !currentUserQuery.isPending ? (
        <AuthActionBanner
          returnTo={APP_ROUTES.overview}
          title="Sign in to view your workspace AOIs, prepared datasets, and assessments"
          description="Public runtime status and NASA provider readiness are live below; workspace records require an authenticated session."
        />
      ) : null}

      <div className="sci-workspace-shell">
        <aside className="sci-rail" aria-label="Runtime configuration summary">
          <section className="sci-panel">
            <div className="sci-panel__header">
              <div>
                <h2 className="sci-panel__title">Runtime &amp; Boundary Spec</h2>
                <p className="sci-panel__subtitle">
                  Live Core API &amp; GHS service contract metadata
                </p>
              </div>
            </div>
            <ul className="workspace-spec-list">
              <li className="workspace-spec-item">
                <span className="workspace-spec-item__label">Core Service</span>
                <span className="workspace-spec-item__value">
                  {systemQuery.data
                    ? `${systemQuery.data.service} v${systemQuery.data.version}`
                    : healthQuery.isError
                      ? 'Unavailable'
                      : 'Loading…'}
                </span>
              </li>
              <li className="workspace-spec-item">
                <span className="workspace-spec-item__label">Environment</span>
                <span className="workspace-spec-item__value">
                  {systemQuery.data?.environment ?? '—'}
                </span>
              </li>
              <li className="workspace-spec-item">
                <span className="workspace-spec-item__label">Default CRS</span>
                <span className="workspace-spec-item__value">
                  {systemQuery.data?.defaultCrs ?? 'EPSG:4326'}
                </span>
              </li>
              <li className="workspace-spec-item">
                <span className="workspace-spec-item__label">Visual Layer Catalog</span>
                <span className="workspace-spec-item__value">
                  {layersQuery.isPending ? 'Loading…' : `${layers.length} layer(s)`}
                </span>
              </li>
              <li className="workspace-spec-item">
                <span className="workspace-spec-item__label">Data Provenance Rule</span>
                <span className="workspace-spec-item__value">
                  NASA GIBS tiles are visual-only; analysis runs on GHS harmonized datasets
                </span>
              </li>
            </ul>
          </section>
        </aside>

        <main className="sci-main-stack">
          <section className="sci-panel">
            <div className="sci-panel__header">
              <div>
                <h2 className="sci-panel__title">Live Workspace &amp; Service Metrics</h2>
                <p className="sci-panel__subtitle">
                  Counts read directly from Core API and Geospatial Harmonization Service
                </p>
              </div>
            </div>

            <div className="sci-kpi-grid">
              <article className="sci-dim-card">
                <div className="sci-dim-card__head">
                  <span className="sci-dim-card__name">Providers Ready</span>
                  <StatusBadge tone={readyProvidersCount > 0 ? 'success' : 'warning'}>
                    {providers.length > 0
                      ? `${readyProvidersCount}/${providers.length}`
                      : 'Unavailable'}
                  </StatusBadge>
                </div>
                <p className="sci-dim-card__value">{readyProvidersCount}</p>
                <p className="sci-dim-card__note">
                  GHS environmental sources with active ingestion capability
                </p>
              </article>

              <article className="sci-dim-card">
                <div className="sci-dim-card__head">
                  <span className="sci-dim-card__name">Saved AOIs</span>
                  <StatusBadge tone="teal">{isAuthenticated ? 'Active' : 'Sign in'}</StatusBadge>
                </div>
                <p className="sci-dim-card__value">{isAuthenticated ? regions.length : '—'}</p>
                <p className="sci-dim-card__note">
                  Regions persisted in Core for discovery and assessment scoping
                </p>
              </article>

              <article className="sci-dim-card">
                <div className="sci-dim-card__head">
                  <span className="sci-dim-card__name">Prepared Datasets</span>
                  <StatusBadge tone="teal">{isAuthenticated ? 'GHS' : 'Sign in'}</StatusBadge>
                </div>
                <p className="sci-dim-card__value">{isAuthenticated ? datasets.length : '—'}</p>
                <p className="sci-dim-card__note">
                  QA-screened temporal datasets available for Scientific Core
                </p>
              </article>

              <article className="sci-dim-card">
                <div className="sci-dim-card__head">
                  <span className="sci-dim-card__name">Completed Assessments</span>
                  <StatusBadge tone="teal">{isAuthenticated ? 'Worker' : 'Sign in'}</StatusBadge>
                </div>
                <p className="sci-dim-card__value">
                  {isAuthenticated ? completedAssessmentsCount : '—'}
                </p>
                <p className="sci-dim-card__note">
                  {isAuthenticated
                    ? `Out of ${assessments.length} persisted run(s) ready for comparison & export`
                    : 'Sign in to inspect your completed scientific analyses'}
                </p>
              </article>
            </div>
          </section>

          <section className="sci-panel">
            <div className="sci-panel__header">
              <div>
                <h2 className="sci-panel__title">End-to-End Scientific Workflow</h2>
                <p className="sci-panel__subtitle">
                  Execute the complete observation-to-report journey directly through the UI
                </p>
              </div>
            </div>

            <div className="sci-kpi-grid">
              <article className="sci-dim-card">
                <div className="sci-dim-card__head">
                  <span className="sci-dim-card__name">1. AOI Selection</span>
                  <StatusBadge tone="neutral">/explore</StatusBadge>
                </div>
                <p className="sci-dim-card__note">
                  Inspect global NASA GIBS contextual layers and draw or select a saved Area of
                  Interest.
                </p>
                <div className="sci-btn-row">
                  <Link to={APP_ROUTES.explore} className="terra-link-reset">
                    <Button variant="secondary">Open Map Explorer</Button>
                  </Link>
                </div>
              </article>

              <article className="sci-dim-card">
                <div className="sci-dim-card__head">
                  <span className="sci-dim-card__name">2. Data Ingestion</span>
                  <StatusBadge tone="neutral">/data-sources</StatusBadge>
                </div>
                <p className="sci-dim-card__note">
                  Discover NASA observations, trigger bounded multi-granule ingestion, QA, and
                  temporal harmonization in GHS.
                </p>
                <div className="sci-btn-row">
                  <Link to={APP_ROUTES.dataSources} className="terra-link-reset">
                    <Button variant="secondary">Open Data Sources</Button>
                  </Link>
                </div>
              </article>

              <article className="sci-dim-card">
                <div className="sci-dim-card__head">
                  <span className="sci-dim-card__name">3. Scientific Assessment</span>
                  <StatusBadge tone="neutral">/assessments</StatusBadge>
                </div>
                <p className="sci-dim-card__note">
                  Execute asynchronous trend, anomaly, recovery, cross-variable, and 4-dimension
                  resilience diagnostics.
                </p>
                <div className="sci-btn-row">
                  <Link to={APP_ROUTES.assessments} className="terra-link-reset">
                    <Button variant="primary">Run Assessment</Button>
                  </Link>
                </div>
              </article>

              <article className="sci-dim-card">
                <div className="sci-dim-card__head">
                  <span className="sci-dim-card__name">4. Compare &amp; Export</span>
                  <StatusBadge tone="neutral">/comparative-analysis · /reports</StatusBadge>
                </div>
                <p className="sci-dim-card__note">
                  Overlay two completed runs for statistical deltas or export JSON, CSV, Markdown,
                  and printable PDF provenance briefs.
                </p>
                <div className="sci-btn-row">
                  <Link to={APP_ROUTES.comparativeAnalysis} className="terra-link-reset">
                    <Button variant="secondary">Compare</Button>
                  </Link>
                  <Link to={APP_ROUTES.reports} className="terra-link-reset">
                    <Button variant="secondary">Reports</Button>
                  </Link>
                </div>
              </article>
            </div>
          </section>

          <section className="sci-panel">
            <div className="sci-panel__header">
              <div>
                <h2 className="sci-panel__title">GHS Environmental Providers</h2>
                <p className="sci-panel__subtitle">
                  Live credential readiness and product availability reported by GHS
                </p>
              </div>
            </div>

            {providersQuery.isPending ? (
              <p className="workspace-config-rail__note">Probing provider status…</p>
            ) : providersQuery.isError ? (
              <div className="sci-banner sci-banner--warning">
                <span>
                  Unable to reach GHS provider registry through Core API. Verify `make dev-full` is
                  running.
                </span>
              </div>
            ) : (
              <div className="provenance-table-wrapper">
                <table className="provenance-table" aria-label="Provider readiness summary">
                  <thead>
                    <tr>
                      <th scope="col">Provider</th>
                      <th scope="col">Status</th>
                      <th scope="col">Authentication</th>
                      <th scope="col">Discovery</th>
                      <th scope="col">Products</th>
                    </tr>
                  </thead>
                  <tbody>
                    {providers.map((provider) => (
                      <tr key={provider.provider}>
                        <td className="provenance-table__primary">
                          {provider.title} ({provider.provider})
                        </td>
                        <td>
                          <StatusBadge tone={providerTone(provider.status)}>
                            {provider.status}
                          </StatusBadge>
                        </td>
                        <td>
                          {provider.authRequired
                            ? provider.authConfigured
                              ? `Configured (${provider.authMechanism})`
                              : `Credentials needed (${provider.authMechanism})`
                            : 'Public / no credential required'}
                        </td>
                        <td>{provider.supportsDiscovery ? 'Supported' : 'Direct request'}</td>
                        <td>{(provider.products ?? []).length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  )
}
