import {
  exportAoiGeoJsonFile,
  formatCoordinatePair,
} from '../../../shared/lib/geojson-utils'
import {
  Check,
  Download,
  Pentagon,
  Square,
  Trash2,
  X,
} from '../../../shared/ui/explorer-icons'
import { useAreaObservationQuery } from '../api/use-map-provider-queries'
import { useExploreStore } from '../model/use-explore-store'

const ROLE_OPTIONS = ['regionA', 'regionB', 'primary'] as const

function roleLabel(role: (typeof ROLE_OPTIONS)[number]): string {
  return role === 'regionA' ? 'Region A' : role === 'regionB' ? 'Region B' : 'Primary'
}

export function InspectorAoiTab() {
  const primaryLayerId = useExploreStore((s) => s.primaryLayerId)
  const dateRangeStart = useExploreStore((s) => s.dateRangeStart)
  const dateRangeEnd = useExploreStore((s) => s.dateRangeEnd)
  const interactionMode = useExploreStore((s) => s.interactionMode)
  const setInteractionMode = useExploreStore((s) => s.setInteractionMode)
  const aois = useExploreStore((s) => s.aois)
  const selectedAoiId = useExploreStore((s) => s.selectedAoiId)
  const setSelectedAoiId = useExploreStore((s) => s.setSelectedAoiId)
  const activeAoiRole = useExploreStore((s) => s.activeAoiRole)
  const setActiveAoiRole = useExploreStore((s) => s.setActiveAoiRole)
  const draftVertices = useExploreStore((s) => s.draftVertices)
  const completeDraftAoi = useExploreStore((s) => s.completeDraftAoi)
  const cancelDraftAoi = useExploreStore((s) => s.cancelDraftAoi)
  const updateAoiRole = useExploreStore((s) => s.updateAoiRole)
  const renameAoi = useExploreStore((s) => s.renameAoi)
  const removeAoi = useExploreStore((s) => s.removeAoi)
  const clearAois = useExploreStore((s) => s.clearAois)

  const selectedAoi = aois.find((item) => item.properties.id === selectedAoiId) ?? aois[0] ?? null
  const areaQuery = useAreaObservationQuery(primaryLayerId, selectedAoi, dateRangeStart, dateRangeEnd)
  const isDrawing = interactionMode === 'draw-polygon' || interactionMode === 'draw-rectangle'

  return (
    <div className="explorer-inspector-stack" role="tabpanel">
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
            className={`explorer-action-btn ${interactionMode === 'draw-polygon' ? 'is-active' : ''}`}
            onClick={() => setInteractionMode('draw-polygon')}
          >
            <Pentagon size={13} />
            <span>Draw Polygon</span>
          </button>
          <button
            type="button"
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
                  disabled={draftVertices.length < 3}
                  onClick={() => completeDraftAoi()}
                >
                  <Check size={13} />
                  <span>Complete</span>
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

      {aois.length === 0 ? (
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
            {aois.map((aoi) => {
              const isSelected = aoi.properties.id === selectedAoi?.properties.id
              return (
                <div
                  key={aoi.properties.id}
                  className={`explorer-aoi-card is-${aoi.properties.role} ${isSelected ? 'is-selected' : ''}`}
                  onClick={() => setSelectedAoiId(aoi.properties.id)}
                >
                  <div className="explorer-aoi-card__head">
                    <input
                      type="text"
                      className="explorer-aoi-name-input"
                      value={aoi.properties.name}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => renameAoi(aoi.properties.id, e.target.value)}
                      aria-label="AOI name"
                    />
                    <button
                      type="button"
                      className="explorer-icon-mini"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeAoi(aoi.properties.id)
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
                        className={`explorer-role-pill is-${role} ${aoi.properties.role === role ? 'is-active' : ''}`}
                        onClick={(e) => {
                          e.stopPropagation()
                          updateAoiRole(aoi.properties.id, role)
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
                      <dd>
                        {formatCoordinatePair(aoi.properties.centroid[0], aoi.properties.centroid[1])}
                      </dd>
                    </div>
                  </dl>
                </div>
              )
            })}
          </div>

          {selectedAoi && areaQuery.data && (
            <div className="explorer-status-banner is-unavailable">
              <strong>Zonal aggregation not connected</strong>
              <p>{areaQuery.data.message}</p>
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
            <button type="button" className="explorer-action-btn" onClick={clearAois}>
              Clear All
            </button>
          </div>
        </>
      )}
    </div>
  )
}
