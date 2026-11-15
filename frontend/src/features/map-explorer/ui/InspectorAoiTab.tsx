import { useRef, useState } from 'react'
import { Link } from 'react-router'
import {
  buildGitHubLoginUrl,
  useCurrentUserQuery,
  useDevSessionLoginMutation,
} from '../../../shared/api/auth'
import { useRegionStatisticsQuery } from '../../../shared/api/regions'
import { useSystemInfoQuery } from '../../../shared/api/system'
import { APP_ROUTES } from '../../../shared/config/routes'
import {
  exportAoiGeoJsonFile,
  formatCoordinatePair,
} from '../../../shared/lib/geojson-utils'
import type { AoiFeature, AoiRole } from '../../../shared/types/geospatial'
import {
  Check,
  Download,
  Pentagon,
  Square,
  Trash2,
  X,
} from '../../../shared/ui/explorer-icons'
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

export function InspectorAoiTab() {
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

  const statisticsQuery = useRegionStatisticsQuery(
    selectedAoi?.properties.id ?? null,
    isAuthenticated && Boolean(selectedAoi),
  )

  const isDrawing = interactionMode === 'draw-polygon' || interactionMode === 'draw-rectangle'

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

          {selectedAoi && isAuthenticated && (
            <div className="explorer-inspector-card">
              <span className="explorer-overline">Region Geometry &amp; Statistics</span>
              {statisticsQuery.isPending ? (
                <p className="explorer-muted-copy">Loading region statistics…</p>
              ) : statisticsQuery.isError ? (
                <div className="explorer-status-banner is-error" role="alert">
                  <strong>Statistics unavailable</strong>
                  <p>{statisticsQuery.error.message}</p>
                  <button
                    type="button"
                    className="explorer-inline-reset"
                    onClick={() => void statisticsQuery.refetch()}
                  >
                    Retry
                  </button>
                </div>
              ) : statisticsQuery.data ? (
                <>
                  <dl className="explorer-kv-list explorer-kv-list--dense">
                    <div>
                      <dt>Vertices / Polygons</dt>
                      <dd>
                        {statisticsQuery.data.vertexCount} / {statisticsQuery.data.polygonCount}
                      </dd>
                    </div>
                    <div>
                      <dt>Area (EPSG:4326)</dt>
                      <dd>{statisticsQuery.data.approxAreaKm2.toLocaleString()} km²</dd>
                    </div>
                    <div>
                      <dt>Available metrics</dt>
                      <dd>{statisticsQuery.data.availableMetrics.join(', ')}</dd>
                    </div>
                  </dl>
                  <div className="explorer-status-banner is-unavailable">
                    <strong>Zonal environmental metrics ({statisticsQuery.data.observationStatus})</strong>
                    <p>{statisticsQuery.data.message}</p>
                  </div>
                  <div className="explorer-aoi-footer">
                    <Link
                      to={`${APP_ROUTES.dataSources}?regionId=${encodeURIComponent(selectedAoi.properties.id)}`}
                      className="explorer-action-btn explorer-action-btn--primary"
                    >
                      Ingest Satellite Data
                    </Link>
                    <Link
                      to={`${APP_ROUTES.assessments}?regionId=${encodeURIComponent(selectedAoi.properties.id)}`}
                      className="explorer-action-btn"
                    >
                      Run Scientific Assessment
                    </Link>
                  </div>
                </>
              ) : null}
            </div>
          )}

          {selectedAoi && !isAuthenticated && (
            <div className="explorer-status-banner is-unavailable">
              <strong>Zonal aggregation not connected</strong>
              <p>
                Regional zonal statistics for &ldquo;{selectedAoi.properties.name}&rdquo; require
                backend dataset ingestion. Geometric properties above are computed in EPSG:4326.
              </p>
            </div>
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
