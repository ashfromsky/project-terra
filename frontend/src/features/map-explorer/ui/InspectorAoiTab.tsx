import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import {
  buildGitHubLoginUrl,
  useCurrentUserQuery,
  useDevSessionLoginMutation,
} from '../../../shared/api/auth'
import { useZonalStatisticsQuery, useZonalTimeseriesQuery } from '../../../shared/api/analytics'
import { toRegionGeometryInput } from '../../../shared/api/regions'
import { useSystemInfoQuery } from '../../../shared/api/system'
import { APP_ROUTES } from '../../../shared/config/routes'
import {
  exportAoiGeoJsonFile,
  formatCoordinatePair,
} from '../../../shared/lib/geojson-utils'
import {
  buildHistogramChartOption,
  buildTimeSeriesChartOption,
} from '../../../shared/lib/scientific-charts'
import type { AoiFeature, AoiRole, MapLayerDefinition } from '../../../shared/types/geospatial'
import {
  Check,
  Download,
  Pentagon,
  Square,
  Trash2,
  X,
} from '../../../shared/ui/explorer-icons'
import { Chart } from '../../../shared/ui/chart'
import { resolveZonalObservation } from '../lib/zonal-observation'
import { useAoiAssessmentRun } from '../model/use-aoi-assessment-run'
import { useAoiWorkspace } from '../model/use-aoi-workspace'
import { useExploreStore } from '../model/use-explore-store'

const ROLE_OPTIONS: readonly AoiRole[] = ['regionA', 'regionB', 'primary']

function roleLabel(role: AoiRole): string {
  return role === 'regionA' ? 'Region A' : role === 'regionB' ? 'Region B' : 'Primary'
}

function DevSessionQuickButton() {
  const devLoginMutation = useDevSessionLoginMutation()
  return (
    <button
      type="button"
      className="explorer-action-btn explorer-action-btn--primary"
      disabled={devLoginMutation.isPending}
      onClick={() => devLoginMutation.mutate()}
    >
      {devLoginMutation.isPending ? 'Starting dev session…' : 'Start Dev Session'}
    </button>
  )
}

interface AoiCardProps {
  aoi: AoiFeature
  isSelected: boolean
  disabled: boolean
  onSelect: () => void
  onRename: (name: string) => Promise<void>
  onRoleChange: (role: AoiRole) => Promise<void>
  onRemove: () => Promise<void>
}

function AoiCard({
  aoi,
  isSelected,
  disabled,
  onSelect,
  onRename,
  onRoleChange,
  onRemove,
}: AoiCardProps) {
  const [draftState, setDraftState] = useState<{ sourceName: string; value: string } | null>(null)
  const skipNextBlurRef = useRef(false)
  const draftName =
    draftState && draftState.sourceName === aoi.properties.name
      ? draftState.value
      : aoi.properties.name

  const commitName = () => {
    if (skipNextBlurRef.current) {
      skipNextBlurRef.current = false
      setDraftState(null)
      return
    }
    const trimmed = draftName.trim()
    setDraftState(null)
    if (!trimmed || trimmed === aoi.properties.name) {
      return
    }
    void onRename(trimmed)
  }

  return (
    <div
      className={`explorer-aoi-card is-${aoi.properties.role} ${isSelected ? 'is-selected' : ''}`}
      onClick={onSelect}
    >
      <div className="explorer-aoi-card__head">
        <input
          type="text"
          className="explorer-aoi-name-input"
          value={draftName}
          disabled={disabled}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) =>
            setDraftState({ sourceName: aoi.properties.name, value: e.target.value })
          }
          onBlur={commitName}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.currentTarget.blur()
            } else if (e.key === 'Escape') {
              skipNextBlurRef.current = true
              setDraftState(null)
              e.currentTarget.blur()
            }
          }}
          aria-label="AOI name"
        />
        <button
          type="button"
          className="explorer-icon-mini"
          disabled={disabled}
          onClick={(e) => {
            e.stopPropagation()
            void onRemove()
          }}
          aria-label={`Delete ${aoi.properties.name}`}
        >
          <Trash2 size={13} />
        </button>
      </div>

      <div className="explorer-aoi-card__roles">
        {ROLE_OPTIONS.map((role) => (
          <button
            key={role}
            type="button"
            disabled={disabled}
            className={`explorer-role-pill is-${role} ${aoi.properties.role === role ? 'is-active' : ''}`}
            onClick={(e) => {
              e.stopPropagation()
              void onRoleChange(role)
            }}
          >
            {roleLabel(role)}
          </button>
        ))}
      </div>

      <dl className="explorer-kv-list explorer-kv-list--dense">
        <div>
          <dt>Source CRS</dt>
          <dd>{aoi.properties.sourceCrs}</dd>
        </div>
        <div>
          <dt>Approx area</dt>
          <dd>{aoi.properties.approxAreaKm2.toLocaleString()} km²</dd>
        </div>
        <div>
          <dt>Centroid</dt>
          <dd>{formatCoordinatePair(aoi.properties.centroid[0], aoi.properties.centroid[1])}</dd>
        </div>
      </dl>
    </div>
  )
}

export function InspectorAoiTab({
  activeLayer,
  catalogLoading,
}: {
  activeLayer: MapLayerDefinition | null
  catalogLoading: boolean
}) {
  const [copiedStatus, setCopiedStatus] = useState<'coords' | 'bounds' | null>(null)
  const interactionMode = useExploreStore((s) => s.interactionMode)
  const setInteractionMode = useExploreStore((s) => s.setInteractionMode)
  const activeAoiRole = useExploreStore((s) => s.activeAoiRole)
  const setActiveAoiRole = useExploreStore((s) => s.setActiveAoiRole)
  const draftVertices = useExploreStore((s) => s.draftVertices)
  const cancelDraftAoi = useExploreStore((s) => s.cancelDraftAoi)

  const currentUserQuery = useCurrentUserQuery()
  const systemInfoQuery = useSystemInfoQuery()
  const currentUser = currentUserQuery.data ?? null
  const oauthConfigured = systemInfoQuery.data?.githubOauthConfigured ?? false

  const {
    aois,
    selectedAoi,
    setSelectedAoiId,
    isAuthenticated,
    isLoadingRegions,
    regionsError,
    refetchRegions,
    syncPending,
    syncError,
    clearSyncError,
    completeDraftAoi,
    updateAoiRole,
    renameAoi,
    removeAoi,
    clearAois,
  } = useAoiWorkspace()

  const primaryLayerId = useExploreStore((s) => s.primaryLayerId)
  const selectedDate = useExploreStore((s) => s.selectedDate)
  const observation = resolveZonalObservation(activeLayer, selectedDate)

  const zonalStatsQuery = useZonalStatisticsQuery({
    metricId: primaryLayerId,
    date: observation.date,
    geometry: selectedAoi ? toRegionGeometryInput(selectedAoi.geometry) : undefined,
    regionId: isAuthenticated ? selectedAoi?.properties.id : undefined,
    enabled: Boolean(selectedAoi) && observation.hasIngestedDataset,
    cacheKey: selectedAoi
      ? `${selectedAoi.properties.id}-${observation.date ?? 'latest'}`
      : undefined,
  })

  const timeseriesQuery = useZonalTimeseriesQuery({
    metricId: primaryLayerId,
    geometry: selectedAoi ? toRegionGeometryInput(selectedAoi.geometry) : undefined,
    regionId: isAuthenticated ? selectedAoi?.properties.id : undefined,
    enabled: Boolean(selectedAoi) && observation.hasIngestedDataset,
    cacheKey: selectedAoi?.properties.id,
  })

  const zonalData = zonalStatsQuery.data
  const displayDate = zonalData?.date ?? observation.displayDate

  const isDrawing = interactionMode === 'draw-polygon' || interactionMode === 'draw-rectangle'

  const navigate = useNavigate()
  const analysisStart = useExploreStore((s) => s.analysisStart)
  const analysisEnd = useExploreStore((s) => s.analysisEnd)
  const setAnalysisPeriod = useExploreStore((s) => s.setAnalysisPeriod)
  const [includeVegetation, setIncludeVegetation] = useState(false)
  const [includeSoilMoisture, setIncludeSoilMoisture] = useState(false)
  const assessmentRun = useAoiAssessmentRun()
  const isSubmitting =
    assessmentRun.phase === 'provisioning' || assessmentRun.phase === 'submitting'

  const handleRunAssessment = async () => {
    if (!selectedAoi || !isAuthenticated) return
    const result = await assessmentRun.run({
      regionId: selectedAoi.properties.id,
      aoiName: selectedAoi.properties.name,
      analysisStart,
      analysisEnd,
      includeVegetation,
      includeSoilMoisture,
    })
    if (!result) return
    const params = new URLSearchParams({
      assessmentId: result.assessment.id,
      regionId: selectedAoi.properties.id,
      start: analysisStart,
      end: analysisEnd,
    })
    navigate(`${APP_ROUTES.assessments}?${params.toString()}`)
  }

  return (
    <div className="explorer-inspector-stack" role="tabpanel">
      {isAuthenticated && currentUser ? (
        <div className="explorer-status-banner is-synced">
          <strong>Synced workspace (@{currentUser.githubLogin})</strong>
          <p>
            Regions persist to TERRA Core API in WGS 84 (EPSG:4326).
            {syncPending ? ' Saving changes…' : ''}
          </p>
        </div>
      ) : (
        <div className="explorer-status-banner">
          <strong>Local session drafts</strong>
          <p>
            {oauthConfigured
              ? 'AOIs stay in this browser session until you sign in with GitHub.'
              : 'AOIs remain in this browser session and can be exported as WGS 84 GeoJSON.'}
          </p>
          {oauthConfigured && (
            <a href={buildGitHubLoginUrl('/explore')} className="explorer-auth-link">
              Sign in with GitHub to save regions
            </a>
          )}
          {systemInfoQuery.data?.devAuthEnabled && !systemInfoQuery.isError && (
            <DevSessionQuickButton />
          )}
        </div>
      )}

      {syncError && (
        <div className="explorer-status-banner is-error" role="alert">
          <div className="explorer-banner-head">
            <strong>Region sync error</strong>
            <button type="button" className="explorer-inline-reset" onClick={clearSyncError}>
              Dismiss
            </button>
          </div>
          <p>{syncError}</p>
        </div>
      )}

      <div className="explorer-inspector-card">
        <div className="explorer-control-row">
          <span className="explorer-control-label">New AOI role</span>
          <div className="explorer-role-pills">
            {ROLE_OPTIONS.map((role) => (
              <button
                key={role}
                type="button"
                className={`explorer-role-pill is-${role} ${activeAoiRole === role ? 'is-active' : ''}`}
                onClick={() => setActiveAoiRole(role)}
              >
                {roleLabel(role)}
              </button>
            ))}
          </div>
        </div>

        <div className="explorer-draw-toolbar">
          <button
            type="button"
            disabled={syncPending}
            className={`explorer-action-btn ${interactionMode === 'draw-polygon' ? 'is-active' : ''}`}
            onClick={() => setInteractionMode('draw-polygon')}
          >
            <Pentagon size={13} />
            <span>Draw Polygon</span>
          </button>
          <button
            type="button"
            disabled={syncPending}
            className={`explorer-action-btn ${interactionMode === 'draw-rectangle' ? 'is-active' : ''}`}
            onClick={() => setInteractionMode('draw-rectangle')}
          >
            <Square size={13} />
            <span>Draw Rectangle</span>
          </button>
        </div>

        {isDrawing && (
          <div className="explorer-draw-guide">
            <p>
              {interactionMode === 'draw-polygon'
                ? `Click map to place polygon vertices (${draftVertices.length} placed). Double-click or press Complete when >= 3 vertices.`
                : draftVertices.length === 0
                  ? 'Click the first corner on the map.'
                  : 'Click the opposite corner on the map to complete rectangle.'}
            </p>
            <div className="explorer-draw-guide__actions">
              {interactionMode === 'draw-polygon' && (
                <button
                  type="button"
                  className="explorer-action-btn explorer-action-btn--primary"
                  disabled={draftVertices.length < 3 || syncPending}
                  onClick={() => void completeDraftAoi()}
                >
                  <Check size={13} />
                  <span>{syncPending ? 'Saving…' : 'Complete'}</span>
                </button>
              )}
              <button type="button" className="explorer-action-btn" onClick={cancelDraftAoi}>
                <X size={13} />
                <span>Cancel</span>
              </button>
            </div>
          </div>
        )}
      </div>

      {isLoadingRegions ? (
        <div className="explorer-state-card" role="status">
          Loading saved regions from TERRA Core API…
        </div>
      ) : regionsError ? (
        <div className="explorer-state-card explorer-state-card--error" role="alert">
          <p className="explorer-state-card__title">Could not load saved regions</p>
          <p className="explorer-muted-copy">{regionsError.message}</p>
          <button
            type="button"
            className="explorer-action-btn"
            onClick={() => void refetchRegions()}
          >
            Retry
          </button>
        </div>
      ) : aois.length === 0 ? (
        <div className="explorer-empty-card">
          <Pentagon size={18} aria-hidden="true" />
          <h3>No Areas of Interest defined</h3>
          <p>
            Draw a WGS 84 polygon or rectangle, or assign a selected country from the Feature tab.
            Exported GeoJSON uses EPSG:4326.
          </p>
        </div>
      ) : (
        <>
          <div className="explorer-aoi-list">
            {aois.map((aoi) => (
              <AoiCard
                key={aoi.properties.id}
                aoi={aoi}
                isSelected={aoi.properties.id === selectedAoi?.properties.id}
                disabled={syncPending}
                onSelect={() => setSelectedAoiId(aoi.properties.id)}
                onRename={(name) => renameAoi(aoi.properties.id, name)}
                onRoleChange={(role) => updateAoiRole(aoi.properties.id, role)}
                onRemove={() => removeAoi(aoi.properties.id)}
              />
            ))}
          </div>

          {selectedAoi && (
            <>
              <div className="explorer-inspector-card">
                <div className="flex items-center justify-between mb-2">
                  <span className="explorer-overline">Physical Zonal Statistics</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-emerald-950/40 text-emerald-300 font-mono">
                    {displayDate}
                  </span>
                </div>
                {observation.dateWasAdjusted && (
                  <p className="explorer-resolution-note">
                    No ingested observation exists for {selectedDate}. Using the latest ingested
                    observation: {observation.date}.
                  </p>
                )}
                {!activeLayer ? (
                  <div className="explorer-status-banner is-unavailable">
                    <strong>
                      {catalogLoading ? 'Loading layer catalog…' : 'Layer catalog unavailable'}
                    </strong>
                    <p>Connect to TERRA Core API to compute physical zonal statistics.</p>
                  </div>
                ) : !observation.hasIngestedDataset ? (
                  <div className="explorer-status-banner is-unavailable">
                    <strong>No ingested raster available</strong>
                    <p>
                      {activeLayer.unavailableReason ??
                        `No physical raster dataset is registered for ${activeLayer.shortName}.`}
                    </p>
                  </div>
                ) : zonalStatsQuery.isPending ? (
                  <p className="explorer-muted-copy">Computing physical raster statistics from COG assets…</p>
                ) : zonalStatsQuery.isError ? (
                  <div className="explorer-status-banner is-error" role="alert">
                    <strong>Zonal aggregation unavailable</strong>
                    <p>{zonalStatsQuery.error.message}</p>
                    <button
                      type="button"
                      className="explorer-inline-reset"
                      onClick={() => void zonalStatsQuery.refetch()}
                    >
                      Retry
                    </button>
                  </div>
                ) : zonalData ? (
                  <>
                    {zonalData.validPixelCount === 0 ? (
                      <div className="explorer-status-banner is-unavailable" role="status">
                        <strong>No valid observations inside this AOI</strong>
                        <p>
                          {zonalData.totalPixelCount === 0
                            ? `The ingested ${activeLayer.shortName} raster for ${zonalData.date} does not intersect this AOI.`
                            : `All ${zonalData.totalPixelCount.toLocaleString()} raster pixels inside this AOI are NoData or masked for ${zonalData.date}.`}
                        </p>
                      </div>
                    ) : (
                      <dl className="explorer-kv-list explorer-kv-list--dense">
                        <div>
                          <dt>Mean</dt>
                          <dd className="font-semibold text-emerald-400">
                            {zonalData.mean != null
                              ? `${zonalData.mean.toFixed(3)} ${zonalData.units ?? ''}`
                              : 'N/A'}
                          </dd>
                        </div>
                        <div>
                          <dt>Median</dt>
                          <dd>
                            {zonalData.median != null
                              ? `${zonalData.median.toFixed(3)} ${zonalData.units ?? ''}`
                              : 'N/A'}
                          </dd>
                        </div>
                        <div>
                          <dt>Min / Max</dt>
                          <dd>
                            {zonalData.min != null && zonalData.max != null
                              ? `[${zonalData.min.toFixed(2)}, ${zonalData.max.toFixed(2)}]`
                              : 'N/A'}
                          </dd>
                        </div>
                        <div>
                          <dt>Std Deviation</dt>
                          <dd>
                            {zonalData.std != null ? zonalData.std.toFixed(3) : 'N/A'}
                          </dd>
                        </div>
                        <div>
                          <dt>P10 / P90</dt>
                          <dd>
                            {zonalData.q10 != null && zonalData.q90 != null
                              ? `${zonalData.q10.toFixed(2)} / ${zonalData.q90.toFixed(2)}`
                              : 'N/A'}
                          </dd>
                        </div>
                        <div>
                          <dt>Valid Coverage</dt>
                          <dd>
                            {(zonalData.validDataCoverage * 100).toFixed(1)}% (
                            {zonalData.validPixelCount.toLocaleString()} px)
                          </dd>
                        </div>
                      </dl>
                    )}

                    {zonalData.histogram.counts.length > 0 && (
                      <div className="live-science-section">
                        <span className="explorer-overline">Pixel Value Distribution</span>
                        <Chart
                          className="live-science-chart live-science-chart--short"
                          option={buildHistogramChartOption({
                            bins: zonalData.histogram.bins,
                            counts: zonalData.histogram.counts,
                            variableName: primaryLayerId,
                            units: zonalData.units ?? undefined,
                          })}
                        />
                      </div>
                    )}

                    {timeseriesQuery.data && timeseriesQuery.data.series.length > 1 && (
                      <div className="live-science-section">
                        <span className="explorer-overline">Temporal Observation Trend</span>
                        <Chart
                          className="live-science-chart"
                          option={buildTimeSeriesChartOption({
                            title: `${primaryLayerId} Multi-temporal`,
                            variableName: primaryLayerId,
                            units: timeseriesQuery.data.units ?? undefined,
                            timestamps: timeseriesQuery.data.series.map((s) => s.date),
                            values: timeseriesQuery.data.series.map((s) => s.mean ?? null),
                          })}
                        />
                      </div>
                    )}
                  </>
                ) : null}

                {activeLayer && !catalogLoading ? (
                  <div className="explorer-aoi-footer">
                    <Link
                      to={`${APP_ROUTES.dataSources}?regionId=${encodeURIComponent(selectedAoi.properties.id)}`}
                      className="explorer-action-btn"
                    >
                      Inspect Data Ingestion
                    </Link>
                  </div>
                ) : null}
              </div>

              <div className="explorer-inspector-card">
                <span className="explorer-overline">Full Scientific Assessment</span>
                <p className="explorer-muted-copy">
                  Provision bounded multi-source observations for this AOI and run full resilience metrics on TERRA Core.
                </p>
                <div className="explorer-analysis-grid">
                  <label className="explorer-analysis-field" htmlFor="aoi-analysis-start">
                    <span>Analysis start</span>
                    <input
                      id="aoi-analysis-start"
                      type="date"
                      value={analysisStart}
                      onChange={(e) => setAnalysisPeriod(e.target.value, analysisEnd)}
                    />
                  </label>
                  <label className="explorer-analysis-field" htmlFor="aoi-analysis-end">
                    <span>Analysis end</span>
                    <input
                      id="aoi-analysis-end"
                      type="date"
                      value={analysisEnd}
                      onChange={(e) => setAnalysisPeriod(analysisStart, e.target.value)}
                    />
                  </label>
                </div>
                <div className="explorer-analysis-toggles">
                  <label>
                    <input
                      type="checkbox"
                      checked={includeVegetation}
                      onChange={(e) => setIncludeVegetation(e.target.checked)}
                    />
                    <span>Vegetation (MODIS)</span>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={includeSoilMoisture}
                      onChange={(e) => setIncludeSoilMoisture(e.target.checked)}
                    />
                    <span>Soil moisture (SMAP)</span>
                  </label>
                </div>
                <p className="explorer-resolution-note">
                  Climate uses NASA POWER (MERRA-2 / CERES). Ingests real bounded granules into GHS and runs assessment pipeline.
                </p>
                <button
                  type="button"
                  className="explorer-action-btn explorer-action-btn--primary"
                  disabled={!isAuthenticated || isSubmitting}
                  onClick={() => void handleRunAssessment()}
                >
                  {assessmentRun.phase === 'provisioning'
                    ? 'Provisioning real observations…'
                    : assessmentRun.phase === 'submitting'
                      ? 'Queuing Scientific Core…'
                      : 'Provision Data & Run Assessment'}
                </button>
                {!isAuthenticated ? (
                  <p className="explorer-resolution-note">
                    Sign in to persist this AOI and submit a scientific assessment.
                  </p>
                ) : null}
                {assessmentRun.phase === 'provisioning' ? (
                  <div className="explorer-status-banner" role="status" aria-live="polite">
                    <strong>Contacting GHS providers</strong>
                    <p>
                      Discovering and retrieving bounded observations for this AOI and period.
                    </p>
                  </div>
                ) : null}
                {assessmentRun.phase === 'submitting' ? (
                  <div className="explorer-status-banner" role="status" aria-live="polite">
                    <strong>Observations ready</strong>
                    <p>
                      {assessmentRun.provision?.datasetIds?.length ?? 0} prepared dataset(s)
                      linked. Queuing the scientific assessment.
                    </p>
                  </div>
                ) : null}
                {assessmentRun.error ? (
                  <div className="explorer-status-banner is-error" role="alert">
                    <strong>Assessment submission failed</strong>
                    <p>{assessmentRun.error}</p>
                    {assessmentRun.provision &&
                    (assessmentRun.provision.steps?.length ?? 0) > 0 ? (
                      <ul className="explorer-provision-steps">
                        {(assessmentRun.provision.steps ?? []).map((step, index) => (
                          <li key={`${step.domain}-${step.provider}-${index}`}>
                            <strong>{step.domain}</strong> · {step.provider} / {step.product} ·{' '}
                            {step.status} — {step.detail}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    <button
                      type="button"
                      className="explorer-inline-reset"
                      onClick={assessmentRun.reset}
                    >
                      Dismiss
                    </button>
                  </div>
                ) : null}
              </div>

              <div className="explorer-inspector-card">
                <span className="explorer-overline">Region Geometry &amp; Boundaries</span>
                <dl className="explorer-kv-list explorer-kv-list--dense">
                  <div>
                    <dt>Source CRS</dt>
                    <dd>{selectedAoi.properties.sourceCrs}</dd>
                  </div>
                  <div>
                    <dt>Area (WGS 84)</dt>
                    <dd>{selectedAoi.properties.approxAreaKm2.toLocaleString()} km²</dd>
                  </div>
                  <div>
                    <dt>Centroid</dt>
                    <dd>
                      {formatCoordinatePair(
                        selectedAoi.properties.centroid[0],
                        selectedAoi.properties.centroid[1],
                      )}
                    </dd>
                  </div>
                </dl>
                <div className="explorer-draw-guide__actions" style={{ marginTop: '8px' }}>
                  <button
                    type="button"
                    className="explorer-action-btn"
                    onClick={() => {
                      const text = JSON.stringify(selectedAoi.geometry)
                      void navigator.clipboard.writeText(text)
                      setCopiedStatus('coords')
                      setTimeout(() => setCopiedStatus(null), 2000)
                    }}
                  >
                    <span>{copiedStatus === 'coords' ? 'Coordinates Copied!' : 'Copy Coordinates (WGS 84)'}</span>
                  </button>
                  <button
                    type="button"
                    className="explorer-action-btn"
                    onClick={() => {
                      const text = JSON.stringify(selectedAoi.properties.bbox)
                      void navigator.clipboard.writeText(text)
                      setCopiedStatus('bounds')
                      setTimeout(() => setCopiedStatus(null), 2000)
                    }}
                  >
                    <span>{copiedStatus === 'bounds' ? 'Bounds Copied!' : 'Copy Bounds'}</span>
                  </button>
                </div>
              </div>
            </>
          )}

          <div className="explorer-aoi-footer">
            <button
              type="button"
              className="explorer-action-btn explorer-action-btn--primary"
              onClick={() => exportAoiGeoJsonFile(aois)}
            >
              <Download size={13} />
              <span>Export WGS 84 GeoJSON</span>
            </button>
            <button
              type="button"
              disabled={syncPending}
              className="explorer-action-btn"
              onClick={() => void clearAois()}
            >
              Clear All
            </button>
          </div>
        </>
      )}
    </div>
  )
}
