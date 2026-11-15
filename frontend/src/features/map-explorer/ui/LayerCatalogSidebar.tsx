import { LAYER_GROUPS } from '../../../entities/layer/model/layer-catalog'
import { useLayerCatalogQuery } from '../../../shared/api/layers'
import type { DataAvailabilityStatus, MapLayerDefinition } from '../../../shared/types/geospatial'
import {
  Eye,
  EyeOff,
  RotateCcw,
  SlidersHorizontal,
  X,
} from '../../../shared/ui/explorer-icons'
import { resolveLayerControlState, useExploreStore } from '../model/use-explore-store'

function getStatusBadgeMeta(layer: MapLayerDefinition): {
  label: string
  toneClass: string
} {
  if (layer.isExperimental) {
    return { label: 'Experimental', toneClass: 'is-experimental' }
  }
  const map: Record<DataAvailabilityStatus, { label: string; toneClass: string }> = {
    connected: { label: 'Connected', toneClass: 'is-connected' },
    preview: { label: 'Unavailable', toneClass: 'is-unavailable' },
    planned: { label: 'Unavailable', toneClass: 'is-unavailable' },
    unavailable: { label: 'Unavailable', toneClass: 'is-unavailable' },
  }
  return map[layer.availabilityStatus]
}

export interface LayerCatalogSidebarProps {
  onZoomToBbox?: (bbox: readonly [number, number, number, number]) => void
}

export function LayerCatalogSidebar({ onZoomToBbox }: LayerCatalogSidebarProps) {
  const leftSidebarOpen = useExploreStore((s) => s.leftSidebarOpen)
  const setLeftSidebarOpen = useExploreStore((s) => s.setLeftSidebarOpen)
  const primaryLayerId = useExploreStore((s) => s.primaryLayerId)
  const setPrimaryLayerId = useExploreStore((s) => s.setPrimaryLayerId)
  const layerStates = useExploreStore((s) => s.layerStates)
  const toggleLayerVisibility = useExploreStore((s) => s.toggleLayerVisibility)
  const setLayerOpacity = useExploreStore((s) => s.setLayerOpacity)
  const setLayerValueRange = useExploreStore((s) => s.setLayerValueRange)
  const resetLayerValueRange = useExploreStore((s) => s.resetLayerValueRange)

  const showGraticules = useExploreStore((s) => s.showGraticules)
  const setShowGraticules = useExploreStore((s) => s.setShowGraticules)
  const showBorders = useExploreStore((s) => s.showBorders)
  const setShowBorders = useExploreStore((s) => s.setShowBorders)
  const showLabels = useExploreStore((s) => s.showLabels)
  const setShowLabels = useExploreStore((s) => s.setShowLabels)
  const showRegionBoundaries = useExploreStore((s) => s.showRegionBoundaries)
  const setShowRegionBoundaries = useExploreStore((s) => s.setShowRegionBoundaries)

  const catalogQuery = useLayerCatalogQuery()
  const layers = catalogQuery.data ?? []

  if (!leftSidebarOpen) {
    return null
  }

  const connectedCount = layers.filter((layer) => layer.availabilityStatus === 'connected').length
  const subtitle = catalogQuery.isPending
    ? 'Connecting to TERRA Core API…'
    : catalogQuery.isError
      ? 'Catalog unavailable · Core API offline'
      : `${connectedCount} / ${layers.length} products connected`

  return (
    <aside
      className="explorer-sidebar explorer-sidebar--left"
      aria-label="Environmental layer catalog"
    >
      <div className="explorer-panel-header">
        <div>
          <h2 className="explorer-panel-title">Layer Catalog</h2>
          <p className="explorer-panel-subtitle">{subtitle}</p>
        </div>
        <button
          type="button"
          className="explorer-panel-close"
          onClick={() => setLeftSidebarOpen(false)}
          aria-label="Collapse layer catalog sidebar"
        >
          <X size={15} />
        </button>
      </div>

      <div className="explorer-sidebar__scroll">
        <section className="explorer-sidebar-section" aria-label="Cartographic overlays">
          <h3 className="explorer-group-heading">Reference Cartography</h3>
          <div className="explorer-overlay-grid">
            <label className="explorer-check-chip">
              <input
                type="checkbox"
                checked={showGraticules}
                onChange={(e) => setShowGraticules(e.target.checked)}
              />
              <span>Graticules</span>
            </label>
            <label className="explorer-check-chip">
              <input
                type="checkbox"
                checked={showBorders}
                onChange={(e) => setShowBorders(e.target.checked)}
              />
              <span>Borders</span>
            </label>
            <label className="explorer-check-chip">
              <input
                type="checkbox"
                checked={showLabels}
                onChange={(e) => setShowLabels(e.target.checked)}
              />
              <span>Labels</span>
            </label>
            <label className="explorer-check-chip">
              <input
                type="checkbox"
                checked={showRegionBoundaries}
                onChange={(e) => setShowRegionBoundaries(e.target.checked)}
              />
              <span>User AOIs</span>
            </label>
          </div>
        </section>

        {catalogQuery.isPending ? (
          <div className="explorer-state-card" role="status">
            Loading environmental layers from TERRA Core API…
          </div>
        ) : catalogQuery.isError ? (
          <div className="explorer-state-card explorer-state-card--error" role="alert">
            <p className="explorer-state-card__title">Could not load layer catalog</p>
            <p className="explorer-muted-copy">
              Ensure the TERRA Core API is running and reachable at <code>/api/v1/layers</code>.
            </p>
            <button
              type="button"
              className="explorer-action-btn"
              onClick={() => void catalogQuery.refetch()}
            >
              Retry
            </button>
          </div>
        ) : layers.length === 0 ? (
          <div className="explorer-state-card">No layers returned by TERRA Core API.</div>
        ) : (
          LAYER_GROUPS.map((group) => {
            const groupLayers = layers.filter((l) => l.groupId === group.id)
            return (
              <section key={group.id} className="explorer-sidebar-section">
                <div className="explorer-group-header">
                  <h3 className="explorer-group-heading">{group.label}</h3>
                  <span className="explorer-group-count">{groupLayers.length}</span>
                </div>
                <div className="explorer-layer-list">
                  {groupLayers.map((layer) => {
                    const isPrimary = layer.id === primaryLayerId
                    const control = resolveLayerControlState(
                      layer,
                      layerStates[layer.id],
                      primaryLayerId,
                    )
                    const badge = getStatusBadgeMeta(layer)

                    return (
                      <div
                        key={layer.id}
                        className={`explorer-layer-item ${isPrimary ? 'is-selected' : ''}`}
                      >
                        <div className="explorer-layer-item__top">
                          <button
                            type="button"
                            className="explorer-layer-item__select"
                            onClick={() => setPrimaryLayerId(layer.id)}
                            aria-expanded={isPrimary}
                          >
                            <span className="explorer-layer-item__name">{layer.name}</span>
                            <span className="explorer-layer-item__meta">
                              {layer.nativeSpatialResolution} · {layer.temporalResolution} · {layer.unit}
                            </span>
                          </button>

                          <button
                            type="button"
                            className={`explorer-layer-vis-btn ${control.visible ? 'is-visible' : ''}`}
                            onClick={() => toggleLayerVisibility(layer.id)}
                            aria-label={
                              control.visible
                                ? `Hide ${layer.shortName}`
                                : `Show ${layer.shortName}`
                            }
                            aria-pressed={control.visible}
                            title={control.visible ? 'Layer visible' : 'Layer hidden'}
                          >
                            {control.visible ? <Eye size={14} /> : <EyeOff size={14} />}
                          </button>
                        </div>

                        <div className="explorer-layer-item__badges">
                          <span className={`explorer-status-pill ${badge.toneClass}`}>
                            {badge.label}
                          </span>
                        </div>

                        {isPrimary && (
                          <div className="explorer-layer-item__details">
                            <p className="explorer-layer-item__desc">{layer.description}</p>

                            {layer.availabilityStatus !== 'connected' && layer.unavailableReason && (
                              <div className="explorer-status-banner is-unavailable">
                                <p>{layer.unavailableReason}</p>
                              </div>
                            )}

                            {layer.datasetBbox && onZoomToBbox && (
                              <button
                                type="button"
                                className="explorer-action-btn"
                                onClick={() => onZoomToBbox(layer.datasetBbox!)}
                              >
                                Zoom to data extent
                              </button>
                            )}

                            <div className="explorer-control-block">
                              <div className="explorer-control-row">
                                <span className="explorer-control-label">
                                  <SlidersHorizontal size={12} aria-hidden="true" />
                                  Opacity
                                </span>
                                <span className="explorer-control-value">
                                  {Math.round(control.opacity * 100)}%
                                </span>
                              </div>
                              <input
                                type="range"
                                min={0}
                                max={100}
                                value={Math.round(control.opacity * 100)}
                                onChange={(e) =>
                                  setLayerOpacity(layer.id, Number(e.target.value) / 100)
                                }
                                aria-label={`${layer.shortName} opacity percentage`}
                                className="explorer-range-slider"
                              />
                            </div>

                            <div className="explorer-control-block">
                              <div className="explorer-control-row">
                                <span className="explorer-control-label">
                                  Display stretch ({layer.unit})
                                </span>
                                <button
                                  type="button"
                                  className="explorer-inline-reset"
                                  onClick={() => resetLayerValueRange(layer.id)}
                                  title="Reset stretch bounds"
                                >
                                  <RotateCcw size={11} />
                                  <span>Reset</span>
                                </button>
                              </div>
                              <div className="explorer-range-inputs">
                                <label className="explorer-num-field">
                                  <span>Min</span>
                                  <input
                                    type="number"
                                    step={layer.valueRange.step}
                                    min={layer.valueRange.min}
                                    max={control.maxValue}
                                    value={control.minValue}
                                    onChange={(e) => {
                                      const v = Number(e.target.value)
                                      if (Number.isFinite(v)) {
                                        setLayerValueRange(layer.id, v, control.maxValue)
                                      }
                                    }}
                                  />
                                </label>
                                <label className="explorer-num-field">
                                  <span>Max</span>
                                  <input
                                    type="number"
                                    step={layer.valueRange.step}
                                    min={control.minValue}
                                    max={layer.valueRange.max}
                                    value={control.maxValue}
                                    onChange={(e) => {
                                      const v = Number(e.target.value)
                                      if (Number.isFinite(v)) {
                                        setLayerValueRange(layer.id, control.minValue, v)
                                      }
                                    }}
                                  />
                                </label>
                              </div>
                            </div>

                            <dl className="explorer-kv-list">
                              <div>
                                <dt>Data source</dt>
                                <dd>{layer.dataSource}</dd>
                              </div>
                              <div>
                                <dt>Time archive</dt>
                                <dd>
                                  {layer.availableTimeRange.start} to {layer.availableTimeRange.end}
                                </dd>
                              </div>
                              <div>
                                <dt>Formats ready</dt>
                                <dd>{layer.supportedTileFormats.join(' · ').toUpperCase()}</dd>
                              </div>
                              <div>
                                <dt>QA policy</dt>
                                <dd>{layer.qaPolicy}</dd>
                              </div>
                            </dl>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </section>
            )
          })
        )}
      </div>
    </aside>
  )
}
