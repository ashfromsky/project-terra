import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  useAssessmentDetailQuery,
  useAssessmentsQuery,
  parseScientificAssessmentResult,
} from '../../shared/api/assessments'
import { useCurrentUserQuery } from '../../shared/api/auth'
import { ApiError, buildApiUrl } from '../../shared/api/client'
import {
  fetchDatasetDownloadUrl,
  useAutoProvisionMutation,
  useDiscoverObservationsMutation,
  useIngestionDetailQuery,
  useIngestionsQuery,
  usePreparedDatasetDetailQuery,
  usePreparedDatasetsQuery,
  useProvidersQuery,
  useStartIngestionMutation,
  type AutoProvisionResponse,
} from '../../shared/api/data-sources'
import type { DiscoverObservationsResponse } from '../../shared/api/contracts'
import { useLayerCatalogQuery } from '../../shared/api/layers'
import { useRegionsQuery } from '../../shared/api/regions'
import { useSystemInfoQuery } from '../../shared/api/system'
import { APP_ROUTES } from '../../shared/config/routes'
import { buildTimeSeriesChartOption } from '../../shared/lib/scientific-charts'
import { AuthActionBanner } from '../../shared/ui/auth-action-banner'
import { Button } from '../../shared/ui/button'
import { Chart } from '../../shared/ui/chart'
import { StatusBadge, type StatusBadgeTone } from '../../shared/ui/status-badge'

function providerStatusTone(status: string): StatusBadgeTone {
  if (status === 'ready') return 'success'
  if (status === 'missing_credentials') return 'warning'
  if (status === 'disabled' || status === 'restricted') return 'error'
  return 'neutral'
}

function ingestionStatusTone(status: string): StatusBadgeTone {
  if (status === 'succeeded') return 'success'
  if (status === 'running') return 'teal'
  if (status === 'pending') return 'warning'
  if (status === 'failed') return 'error'
  return 'neutral'
}

function layerAvailabilityTone(status: string): StatusBadgeTone {
  if (status === 'connected') return 'success'
  if (status === 'preview') return 'warning'
  if (status === 'unavailable') return 'error'
  return 'neutral'
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

export function DataSourcesPage() {
  const [searchParams] = useSearchParams()
  const initialRegionParam = searchParams.get('regionId') ?? ''

  const systemInfoQuery = useSystemInfoQuery()
  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)

  const providersQuery = useProvidersQuery()
  const layersQuery = useLayerCatalogQuery()
  const regionsQuery = useRegionsQuery(isAuthenticated)
  const ingestionsQuery = useIngestionsQuery(isAuthenticated)
  const datasetsQuery = usePreparedDatasetsQuery(isAuthenticated)
  const assessmentsQuery = useAssessmentsQuery(isAuthenticated)

  const discoverMutation = useDiscoverObservationsMutation()
  const startIngestionMutation = useStartIngestionMutation()
  const autoProvisionMutation = useAutoProvisionMutation()

  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedProduct, setSelectedProduct] = useState('')
  const [selectedRegionId, setSelectedRegionId] = useState(initialRegionParam)
  const [bboxText, setBboxText] = useState('24.0, 48.0, 25.0, 49.0')
  const [startDate, setStartDate] = useState('2024-06-01')
  const [endDate, setEndDate] = useState('2024-08-31')
  const [maxGranules, setMaxGranules] = useState(48)
  const [targetCadence, setTargetCadence] = useState('monthly')
  const [runType, setRunType] = useState('Final')
  const [overpass, setOverpass] = useState('AM')
  const [parametersText, setParametersText] = useState('T2M, PRECTOTCORR')
  const [executeNow, setExecuteNow] = useState(false)

  const [discoveryResult, setDiscoveryResult] = useState<DiscoverObservationsResponse | null>(null)
  const [provisionResult, setProvisionResult] = useState<AutoProvisionResponse | null>(null)
  const [selectedOperationId, setSelectedOperationId] = useState<string | null>(null)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [downloadingDatasetId, setDownloadingDatasetId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [groupFilter, setGroupFilter] = useState('all')
  const [selectedAssessmentId, setSelectedAssessmentId] = useState<string | null>(null)

  const providers = useMemo(() => providersQuery.data ?? [], [providersQuery.data])
  const effectiveProvider = useMemo(() => {
    if (selectedProvider && providers.some((p) => p.provider === selectedProvider)) {
      return selectedProvider
    }
    const ready = providers.find((p) => p.status === 'ready' && p.enabled)
    return ready?.provider ?? providers[0]?.provider ?? 'nasa_power'
  }, [providers, selectedProvider])

  const activeProviderMeta = useMemo(
    () => providers.find((p) => p.provider === effectiveProvider) ?? null,
    [providers, effectiveProvider],
  )

  const effectiveProduct = useMemo(() => {
    const registered = activeProviderMeta?.registeredProducts ?? []
    if (selectedProduct && registered.includes(selectedProduct)) {
      return selectedProduct
    }
    return registered[0] ?? ''
  }, [activeProviderMeta, selectedProduct])

  const ingestions = useMemo(() => ingestionsQuery.data ?? [], [ingestionsQuery.data])
  const activeOperationId = selectedOperationId ?? ingestions[0]?.id ?? null
  const activeOperationQuery = useIngestionDetailQuery(
    activeOperationId,
    isAuthenticated && Boolean(activeOperationId),
  )
  const activeOperation =
    activeOperationQuery.data ??
    ingestions.find((item) => item.id === activeOperationId) ??
    null

  const preparedDatasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])
  const effectiveDatasetId =
    selectedDatasetId ??
    activeOperation?.datasetId ??
    preparedDatasets[0]?.datasetId ??
    null
  const datasetDetailQuery = usePreparedDatasetDetailQuery(
    effectiveDatasetId,
    isAuthenticated && Boolean(effectiveDatasetId),
  )
  const activeDataset =
    datasetDetailQuery.data ??
    preparedDatasets.find((d) => d.datasetId === effectiveDatasetId) ??
    null

  const activeDatasetPreview = activeDataset?.timeSeriesPreviews?.[0] ?? null
  const datasetChartOption = useMemo(() => {
    const timestamps = activeDatasetPreview?.timestamps ?? []
    const values = activeDatasetPreview?.values ?? []
    if (!activeDatasetPreview || timestamps.length === 0) return null
    return buildTimeSeriesChartOption({
      title: `${activeDataset?.product ?? 'Dataset'} · ${activeDatasetPreview.variable}`,
      variableName: activeDatasetPreview.variable,
      units: activeDatasetPreview.units ?? undefined,
      timestamps,
      values,
    })
  }, [activeDataset?.product, activeDatasetPreview])

  const handleDownloadDataset = async (datasetId: string) => {
    setActionError(null)
    setDownloadingDatasetId(datasetId)
    try {
      const info = await fetchDatasetDownloadUrl(datasetId)
      const targetUrl = info.presigned ? info.downloadUrl : buildApiUrl(info.downloadUrl)
      const anchor = document.createElement('a')
      anchor.href = targetUrl
      anchor.download = info.filename
      if (info.presigned) {
        anchor.target = '_blank'
        anchor.rel = 'noopener noreferrer'
      }
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to prepare dataset download.')
    } finally {
      setDownloadingDatasetId(null)
    }
  }

  const layers = useMemo(() => layersQuery.data ?? [], [layersQuery.data])
  const availableGroups = useMemo(() => {
    const groups = new Set<string>(['all'])
    layers.forEach((layer) => groups.add(layer.groupId))
    return Array.from(groups)
  }, [layers])
  const filteredLayers = useMemo(
    () => (groupFilter === 'all' ? layers : layers.filter((l) => l.groupId === groupFilter)),
    [groupFilter, layers],
  )

  const activeAssessmentId =
    selectedAssessmentId ?? assessmentsQuery.data?.[0]?.id ?? null
  const assessmentDetailQuery = useAssessmentDetailQuery(
    activeAssessmentId,
    isAuthenticated && Boolean(activeAssessmentId),
  )
  const parsedDetail = useMemo(
    () => parseScientificAssessmentResult(assessmentDetailQuery.data?.result),
    [assessmentDetailQuery.data?.result],
  )

  const parseManualBbox = (): [number, number, number, number] | null => {
    if (selectedRegionId) return null
    const parts = bboxText
      .split(',')
      .map((item) => Number(item.trim()))
      .filter((num) => Number.isFinite(num))
    if (parts.length !== 4) {
      throw new Error('Bounding box must have 4 finite numbers: minLon, minLat, maxLon, maxLat.')
    }
    return [parts[0]!, parts[1]!, parts[2]!, parts[3]!]
  }

  const handleDiscover = async () => {
    setActionError(null)
    try {
      const manualBbox = parseManualBbox()
      const res = await discoverMutation.mutateAsync({
        provider: effectiveProvider,
        product: effectiveProduct,
        regionId: selectedRegionId || null,
        bbox: manualBbox,
        startTime: `${startDate}T00:00:00Z`,
        endTime: `${endDate}T23:59:59Z`,
        limit: 20,
      })
      setDiscoveryResult(res)
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : String(cause)
      setActionError(msg)
    }
  }

  const handleStartIngestion = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setActionError(null)
    try {
      const manualBbox = parseManualBbox()
      const parsedParams = parametersText
        .split(',')
        .map((p) => p.trim())
        .filter((p) => p.length > 0)
      const created = await startIngestionMutation.mutateAsync({
        provider: effectiveProvider,
        product: effectiveProduct,
        regionId: selectedRegionId || null,
        bbox: manualBbox,
        startTime: `${startDate}T00:00:00Z`,
        endTime: `${endDate}T23:59:59Z`,
        maxGranules,
        targetCadence: targetCadence || null,
        runType: effectiveProvider === 'gpm_imerg' ? runType : null,
        overpass: effectiveProvider === 'smap' ? overpass : null,
        parameters: effectiveProvider === 'nasa_power' ? parsedParams : [],
        executeNow,
      })
      setSelectedOperationId(created.id)
      if (created.datasetId) {
        setSelectedDatasetId(created.datasetId)
      }
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : String(cause)
      setActionError(msg)
    }
  }

  const handleAutoProvision = async () => {
    setActionError(null)
    try {
      const manualBbox = parseManualBbox()
      const res = await autoProvisionMutation.mutateAsync({
        regionId: selectedRegionId || null,
        bbox: manualBbox,
        analysisStart: `${startDate}T00:00:00Z`,
        analysisEnd: `${endDate}T23:59:59Z`,
        targetCadence: targetCadence === 'native' ? 'monthly' : targetCadence,
        baselineType: 'fixed_reference',
        referenceStart: null,
        referenceEnd: null,
        minReferenceYears: 3,
        qaLevel: 'strict',
        existingDatasetIds: [],
        desiredDomains: ['climate', 'precipitation', 'soil_moisture', 'vegetation'],
        maxGranulesPerProduct: maxGranules,
      })
      setProvisionResult(res)
      if ((res.datasetIds ?? []).length > 0) {
        setSelectedDatasetId(res.datasetIds![0]!)
      }
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : String(cause)
      setActionError(msg)
    }
  }

  return (
    <div className="workspace-page">
      <section className="workspace-context-bar" aria-label="Data sources context">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading">
            Satellite Discovery, Ingestion &amp; Dataset Provenance
          </h1>
          <p className="workspace-context-bar__breadcrumb">
            Data Sources / Core API ↔ Geospatial Harmonization Service (GHS) / Real Observation
            Pipeline
          </p>
        </div>
        <div className="workspace-context-bar__actions">
          <Link to={APP_ROUTES.explore} className="terra-link-reset">
            <Button variant="secondary">Explore Map &amp; AOIs</Button>
          </Link>
          <Link to={APP_ROUTES.assessments} className="terra-link-reset">
            <Button variant="primary">Scientific Assessments</Button>
          </Link>
        </div>
      </section>

      <div className="sci-main-stack">
        <section className="sci-panel" aria-labelledby="provider-readiness-heading">
          <div className="sci-panel__header">
            <div>
              <h2 id="provider-readiness-heading" className="sci-panel__title">
                Environmental Provider Capabilities &amp; Runtime Health
              </h2>
              <p className="sci-panel__subtitle">
                Live provider readiness reported via{' '}
                <code className="sci-code-chip">GET /api/v1/data-sources/providers</code> (Core HTTP
                bridge to GHS under ADR-0002).
              </p>
            </div>
            {systemInfoQuery.data ? (
              <StatusBadge tone="teal">
                {systemInfoQuery.data.service} v{systemInfoQuery.data.version} ·{' '}
                {systemInfoQuery.data.environment}
              </StatusBadge>
            ) : null}
          </div>

          {providersQuery.isPending ? (
            <p className="sci-panel__subtitle" aria-live="polite">
              Querying Geospatial Harmonization Service providers…
            </p>
          ) : providersQuery.isError ? (
            <div className="sci-banner sci-banner--error" role="alert">
              Could not reach GHS providers via Core:{' '}
              {providersQuery.error instanceof ApiError
                ? providersQuery.error.message
                : String(providersQuery.error)}
            </div>
          ) : (
            <div className="sci-kpi-grid">
              {providers.map((prov) => (
                <article key={prov.provider} className="sci-dim-card">
                  <div className="sci-dim-card__head">
                    <span className="sci-dim-card__name">{prov.title}</span>
                    <StatusBadge tone={providerStatusTone(prov.status)}>{prov.status}</StatusBadge>
                  </div>
                  <p className="sci-dim-card__note">
                    Provider: <code className="sci-code-chip">{prov.provider}</code> · Auth:{' '}
                    {prov.authRequired
                      ? prov.authConfigured
                        ? `${prov.authMechanism} configured`
                        : `${prov.authMechanism} missing`
                      : 'Public access'}
                  </p>
                  <p className="sci-dim-card__note">
                    Products: {(prov.registeredProducts ?? []).join(', ') || 'None'}
                  </p>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="sci-workspace-shell" aria-label="Observation discovery and ingestion">
          <aside className="sci-rail">
            <div>
              <h2 className="workspace-config-rail__title">Discover &amp; Ingest Observations</h2>
              <p className="workspace-config-rail__subtitle">
                Search real satellite granules, launch bounded multi-granule harmonization in GHS,
                and register datasets for Scientific Assessments.
              </p>
            </div>

            {currentUserQuery.isPending ? (
              <p className="sci-dim-card__note" aria-live="polite">
                Checking session…
              </p>
            ) : !isAuthenticated ? (
              <AuthActionBanner
                returnTo={APP_ROUTES.dataSources}
                title="Sign in required for discovery and ingestion"
                description="Sign in to select saved AOIs, run NASA observation discovery, and submit GHS ingestion jobs."
              />
            ) : (
              <form className="sci-form" onSubmit={handleStartIngestion}>
                <div className="sci-field">
                  <label className="sci-label" htmlFor="ingest-region">
                    Area of Interest (AOI)
                  </label>
                  <select
                    id="ingest-region"
                    className="sci-select"
                    value={selectedRegionId}
                    onChange={(e) => setSelectedRegionId(e.target.value)}
                  >
                    <option value="">Custom WGS 84 Bounding Box</option>
                    {(regionsQuery.data ?? []).map((reg) => (
                      <option key={reg.id} value={reg.id}>
                        {reg.name} ({reg.approxAreaKm2.toFixed(0)} km²)
                      </option>
                    ))}
                  </select>
                </div>

                {!selectedRegionId ? (
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-bbox">
                      WGS 84 BBox (minLon, minLat, maxLon, maxLat)
                    </label>
                    <input
                      id="ingest-bbox"
                      className="sci-input"
                      type="text"
                      value={bboxText}
                      onChange={(e) => setBboxText(e.target.value)}
                    />
                  </div>
                ) : null}

                <div className="sci-field-row">
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-provider">
                      Provider
                    </label>
                    <select
                      id="ingest-provider"
                      className="sci-select"
                      value={effectiveProvider}
                      onChange={(e) => {
                        setSelectedProvider(e.target.value)
                        setSelectedProduct('')
                        setDiscoveryResult(null)
                      }}
                    >
                      {providers.map((p) => (
                        <option key={p.provider} value={p.provider}>
                          {p.provider} ({p.status})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-product">
                      Product
                    </label>
                    <select
                      id="ingest-product"
                      className="sci-select"
                      value={effectiveProduct}
                      onChange={(e) => setSelectedProduct(e.target.value)}
                    >
                      {(activeProviderMeta?.registeredProducts ?? []).map((prod) => (
                        <option key={prod} value={prod}>
                          {prod}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="sci-field-row">
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-start">
                      Start date
                    </label>
                    <input
                      id="ingest-start"
                      className="sci-input"
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                    />
                  </div>
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-end">
                      End date
                    </label>
                    <input
                      id="ingest-end"
                      className="sci-input"
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                    />
                  </div>
                </div>

                <div className="sci-field-row">
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-cadence">
                      Target temporal cadence
                    </label>
                    <select
                      id="ingest-cadence"
                      className="sci-select"
                      value={targetCadence}
                      onChange={(e) => setTargetCadence(e.target.value)}
                    >
                      <option value="native">Native cadence</option>
                      <option value="daily">Daily</option>
                      <option value="monthly">Monthly</option>
                    </select>
                  </div>

                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-max-granules">
                      Max granules (1–256)
                    </label>
                    <input
                      id="ingest-max-granules"
                      className="sci-input"
                      type="number"
                      min={1}
                      max={256}
                      value={maxGranules}
                      onChange={(e) =>
                        setMaxGranules(Math.max(1, Math.min(256, Number(e.target.value) || 1)))
                      }
                    />
                  </div>
                </div>

                {effectiveProvider === 'gpm_imerg' ? (
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-run-type">
                      IMERG Run Type
                    </label>
                    <select
                      id="ingest-run-type"
                      className="sci-select"
                      value={runType}
                      onChange={(e) => setRunType(e.target.value)}
                    >
                      <option value="Final">Final (Research-grade)</option>
                      <option value="Late">Late</option>
                      <option value="Early">Early</option>
                    </select>
                  </div>
                ) : null}

                {effectiveProvider === 'smap' ? (
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-overpass">
                      SMAP Overpass
                    </label>
                    <select
                      id="ingest-overpass"
                      className="sci-select"
                      value={overpass}
                      onChange={(e) => setOverpass(e.target.value)}
                    >
                      <option value="AM">AM (06:00 local, recommended baseline)</option>
                      <option value="PM">PM (18:00 local)</option>
                    </select>
                  </div>
                ) : null}

                {effectiveProvider === 'nasa_power' ? (
                  <div className="sci-field">
                    <label className="sci-label" htmlFor="ingest-power-params">
                      NASA POWER parameters (comma-separated)
                    </label>
                    <input
                      id="ingest-power-params"
                      className="sci-input"
                      type="text"
                      value={parametersText}
                      onChange={(e) => setParametersText(e.target.value)}
                    />
                  </div>
                ) : null}

                <label className="sci-checkbox-row">
                  <input
                    type="checkbox"
                    checked={executeNow}
                    onChange={(e) => setExecuteNow(e.target.checked)}
                  />
                  Run synchronously (otherwise queued to GHS Worker)
                </label>

                {actionError ? (
                  <div className="sci-banner sci-banner--error" role="alert">
                    {actionError}
                  </div>
                ) : null}

                <div className="sci-btn-row">
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={discoverMutation.isPending || !effectiveProduct}
                    onClick={() => void handleDiscover()}
                  >
                    {discoverMutation.isPending ? 'Searching…' : 'Discover Observations'}
                  </Button>
                  <Button
                    type="submit"
                    variant="primary"
                    disabled={startIngestionMutation.isPending || !effectiveProduct}
                  >
                    {startIngestionMutation.isPending ? 'Submitting…' : 'Start Ingestion'}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={autoProvisionMutation.isPending}
                    onClick={() => void handleAutoProvision()}
                  >
                    {autoProvisionMutation.isPending
                      ? 'Auto-Provisioning…'
                      : 'Auto-Provision Bundle'}
                  </Button>
                </div>
              </form>
            )}

            {isAuthenticated ? (
              <>
                <hr className="workspace-divider" />
                <div>
                  <h2 className="workspace-config-rail__title">Ingestion Operations</h2>
                  <p className="workspace-config-rail__subtitle">
                    Live job queue tracked by Core and executed in GHS Worker.
                  </p>
                </div>

                {ingestions.length === 0 ? (
                  <p className="sci-dim-card__note">
                    No ingestion jobs submitted yet. Discover observations above and start one.
                  </p>
                ) : (
                  <ul className="sci-run-list">
                    {ingestions.map((op) => {
                      const isSelected = op.id === activeOperation?.id
                      return (
                        <li key={op.id}>
                          <button
                            type="button"
                            className={`sci-run-item ${isSelected ? 'sci-run-item--active' : ''}`.trim()}
                            onClick={() => {
                              setSelectedOperationId(op.id)
                              if (op.datasetId) setSelectedDatasetId(op.datasetId)
                            }}
                          >
                            <div className="sci-run-item__top">
                              <span className="sci-run-item__title">
                                {op.provider} · {op.product}
                              </span>
                              <StatusBadge tone={ingestionStatusTone(op.status)}>
                                {op.status} ({Math.round(op.progressPct)}%)
                              </StatusBadge>
                            </div>
                            <span className="sci-run-item__meta">
                              Job {op.ghsJobId.slice(0, 8)} · {formatDate(op.updatedAt)}
                            </span>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </>
            ) : null}
          </aside>

          <div className="sci-main-stack">
            {provisionResult ? (
              <section className="sci-panel" aria-label="Auto-provisioning results">
                <div className="sci-panel__header">
                  <div>
                    <h2 className="sci-panel__title">Adaptive Bundle Provisioning Outcome</h2>
                    <p className="sci-panel__subtitle">
                      Window: {provisionResult.provisionStart.slice(0, 10)} →{' '}
                      {provisionResult.provisionEnd.slice(0, 10)}
                      {provisionResult.windowExpansionReason
                        ? ` · ${provisionResult.windowExpansionReason}`
                        : ''}
                    </p>
                  </div>
                  <StatusBadge tone="teal">
                    {(provisionResult.datasetIds ?? []).length} dataset(s)
                  </StatusBadge>
                </div>
                <div className="provenance-table-wrapper">
                  <table className="provenance-table">
                    <thead>
                      <tr>
                        <th scope="col">Domain</th>
                        <th scope="col">Provider · Product</th>
                        <th scope="col">Status</th>
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
                          <td style={{ whiteSpace: 'normal', minWidth: 240 }}>{step.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}

            {discoveryResult ? (
              <section className="sci-panel" aria-label="Discovered satellite observations">
                <div className="sci-panel__header">
                  <div>
                    <h2 className="sci-panel__title">
                      Discovered Observations · {discoveryResult.provider} /{' '}
                      {discoveryResult.product}
                    </h2>
                    <p className="sci-panel__subtitle">
                      Found {discoveryResult.count} matching granules within bbox [
                      {discoveryResult.bbox.map((v) => v.toFixed(2)).join(', ')}].
                    </p>
                  </div>
                  <StatusBadge tone="teal">{discoveryResult.count} found</StatusBadge>
                </div>

                {(discoveryResult.observations ?? []).length === 0 ? (
                  <div className="sci-banner sci-banner--neutral">
                    No granules matched the selected AOI and time window. Try expanding the date
                    range or verifying provider availability.
                  </div>
                ) : (
                  <div className="provenance-table-wrapper">
                    <table className="provenance-table">
                      <thead>
                        <tr>
                          <th scope="col">Observation / Granule</th>
                          <th scope="col">Time Window</th>
                          <th scope="col">Query Mode</th>
                          <th scope="col">Access</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(discoveryResult.observations ?? []).slice(0, 12).map((obs) => (
                          <tr key={obs.observationId}>
                            <td className="provenance-table__primary">
                              <div>{obs.title}</div>
                              <div className="sci-run-item__meta">{obs.observationId}</div>
                            </td>
                            <td>
                              {formatDate(obs.timeStart)} → {formatDate(obs.timeEnd)}
                            </td>
                            <td>{obs.queryMode ?? '—'}</td>
                            <td>{obs.accessHint ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            ) : null}

            {activeOperation ? (
              <section className="sci-panel" aria-label="Selected ingestion job status">
                <div className="sci-panel__header">
                  <div>
                    <h2 className="sci-panel__title">
                      Ingestion Operation · {activeOperation.provider} / {activeOperation.product}
                    </h2>
                    <p className="sci-panel__subtitle">
                      GHS Job <code className="sci-code-chip">{activeOperation.ghsJobId}</code> ·
                      Updated {formatDate(activeOperation.updatedAt)}
                    </p>
                  </div>
                  <StatusBadge tone={ingestionStatusTone(activeOperation.status)}>
                    {activeOperation.status} ({Math.round(activeOperation.progressPct)}%)
                  </StatusBadge>
                </div>

                <div
                  className="sci-progress-track"
                  role="progressbar"
                  aria-valuenow={Math.round(activeOperation.progressPct)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className="sci-progress-fill"
                    style={{ width: `${Math.min(100, Math.max(4, activeOperation.progressPct))}%` }}
                  />
                </div>

                {activeOperation.errorMessage ? (
                  <div className="sci-banner sci-banner--error" role="alert">
                    <strong>
                      Ingestion failed
                      {activeOperation.errorCategory ? ` (${activeOperation.errorCategory})` : ''}
                    </strong>
                    <span>{activeOperation.errorMessage}</span>
                  </div>
                ) : null}

                {activeOperation.datasetId ? (
                  <div className="sci-banner sci-banner--teal">
                    <div className="sci-panel__header">
                      <span>
                        Prepared GHS Dataset:{' '}
                        <code className="sci-code-chip">{activeOperation.datasetId}</code>
                        {activeOperation.datasetSummary
                          ? ` · ${activeOperation.datasetSummary.observationCount} observations`
                          : ''}
                      </span>
                      <Link
                        to={`${APP_ROUTES.assessments}?datasetId=${encodeURIComponent(activeOperation.datasetId)}${activeOperation.regionId ? `&regionId=${encodeURIComponent(activeOperation.regionId)}` : ''}`}
                        className="terra-link-reset"
                      >
                        <Button variant="primary">Use in Scientific Assessment</Button>
                      </Link>
                    </div>
                  </div>
                ) : null}
              </section>
            ) : null}

            <section className="sci-panel" aria-labelledby="prepared-datasets-heading">
              <div className="sci-panel__header">
                <div>
                  <h2 id="prepared-datasets-heading" className="sci-panel__title">
                    Prepared Harmonized Datasets
                  </h2>
                  <p className="sci-panel__subtitle">
                    Quality-checked AOI datasets ready for Scientific Core via{' '}
                    <code className="sci-code-chip">GET /api/v1/data-sources/datasets</code>.
                  </p>
                </div>
                {isAuthenticated ? (
                  <StatusBadge tone="teal">{preparedDatasets.length} datasets</StatusBadge>
                ) : null}
              </div>

              {!isAuthenticated ? (
                <p className="sci-dim-card__note">
                  Sign in above to inspect prepared GHS datasets and time-series previews.
                </p>
              ) : datasetsQuery.isPending ? (
                <p className="sci-panel__subtitle" aria-live="polite">
                  Loading prepared datasets…
                </p>
              ) : datasetsQuery.isError ? (
                <div className="sci-banner sci-banner--error" role="alert">
                  Failed to load prepared datasets:{' '}
                  {datasetsQuery.error instanceof ApiError
                    ? datasetsQuery.error.message
                    : String(datasetsQuery.error)}
                </div>
              ) : preparedDatasets.length === 0 ? (
                <div className="sci-banner sci-banner--neutral">
                  No prepared datasets exist in GHS yet. Submit an ingestion job to build one.
                </div>
              ) : (
                <div className="sci-main-stack">
                  <div className="provenance-table-wrapper">
                    <table className="provenance-table">
                      <thead>
                        <tr>
                          <th scope="col">Product &amp; ID</th>
                          <th scope="col">Variables</th>
                          <th scope="col">Cadence &amp; Window</th>
                          <th scope="col">Obs / Valid %</th>
                          <th scope="col">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preparedDatasets.map((ds) => (
                          <tr key={ds.datasetId}>
                            <td className="provenance-table__primary">
                              <div>
                                {ds.provider} · {ds.product}
                              </div>
                              <div className="sci-run-item__meta">{ds.datasetId}</div>
                            </td>
                            <td>
                              <div>{(ds.variables ?? []).join(', ') || '—'}</div>
                              <div className="sci-run-item__meta">
                                QA: {(ds.qaLayersPresent ?? []).join(', ') || 'None'}
                              </div>
                            </td>
                            <td>
                              {ds.temporalCadence ?? '—'} ·{' '}
                              {ds.temporalStart?.slice(0, 10) ?? '—'} to{' '}
                              {ds.temporalEnd?.slice(0, 10) ?? '—'}
                              {ds.spanYears !== null && ds.spanYears !== undefined
                                ? ` (${ds.spanYears.toFixed(1)} yr)`
                                : ''}
                            </td>
                            <td>
                              {ds.observationCount} obs ·{' '}
                              {ds.validFraction !== null && ds.validFraction !== undefined
                                ? `${(ds.validFraction * 100).toFixed(1)}%`
                                : '—'}
                            </td>
                            <td>
                              <div className="sci-btn-row">
                                <Button
                                  type="button"
                                  variant="secondary"
                                  onClick={() => setSelectedDatasetId(ds.datasetId)}
                                >
                                  Inspect
                                </Button>
                                <Button
                                  type="button"
                                  variant="secondary"
                                  disabled={downloadingDatasetId === ds.datasetId}
                                  onClick={() => void handleDownloadDataset(ds.datasetId)}
                                >
                                  {downloadingDatasetId === ds.datasetId ? 'Preparing…' : 'Download'}
                                </Button>
                                <Link
                                  to={`${APP_ROUTES.assessments}?datasetId=${encodeURIComponent(ds.datasetId)}${ds.regionId ? `&regionId=${encodeURIComponent(ds.regionId)}` : ''}`}
                                  className="terra-link-reset"
                                >
                                  <Button type="button" variant="primary">
                                    Assess
                                  </Button>
                                </Link>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {activeDataset ? (
                    <div className="sci-dim-card">
                      <div className="sci-dim-card__head">
                        <span className="sci-dim-card__name">
                          Dataset Preview · {activeDataset.product} ({activeDataset.datasetId})
                        </span>
                        <StatusBadge tone="neutral">
                          CRS: {activeDataset.spatialCrs ?? 'unknown'} ·{' '}
                          {activeDataset.nominalResolutionM
                            ? `${activeDataset.nominalResolutionM} m`
                            : 'native res'}
                        </StatusBadge>
                      </div>
                      {(activeDataset.warnings ?? []).length > 0 ? (
                        <div className="sci-banner sci-banner--warning">
                          {(activeDataset.warnings ?? []).join(' ')}
                        </div>
                      ) : null}
                      {datasetChartOption ? (
                        <Chart option={datasetChartOption} className="sci-chart-box--compact" />
                      ) : (
                        <p className="sci-dim-card__note">
                          No scalar AOI time-series preview attached to this dataset.
                        </p>
                      )}
                    </div>
                  ) : null}
                </div>
              )}
            </section>
          </div>
        </section>

        <section className="provenance-table-card" aria-labelledby="prov-heading">
          <div className="provenance-table-card__header">
            <div>
              <h2 id="prov-heading" className="provenance-table-card__title">
                Core Layer &amp; Visualization Catalog
              </h2>
              <p className="provenance-table-card__subtitle">
                Live catalog metadata from Core API — contextual tile imagery complements
                quantitative GHS datasets above.
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
            <AuthActionBanner
              returnTo={APP_ROUTES.dataSources}
              description="Sign in to inspect persisted assessment quality screening and dataset provenance."
            />
          ) : assessmentsQuery.isPending || assessmentDetailQuery.isPending ? (
            <p className="sci-panel__subtitle" aria-live="polite">
              Loading assessment provenance…
            </p>
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
                  {assessmentDetailQuery.data?.status}).
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
              {assessmentDetailQuery.data?.status ?? 'unknown'}).
            </p>
          )}
        </section>
      </div>
    </div>
  )
}

export default DataSourcesPage
