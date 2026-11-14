import { useCallback, useEffect, useMemo, useRef } from 'react'
import type { MapRenderState } from '../../entities/map/model/map-renderer'
import { useExploreUrlSync } from '../../features/map-explorer/lib/use-explore-url-sync'
import { useAoiWorkspace } from '../../features/map-explorer/model/use-aoi-workspace'
import {
  resolveLayerControlState,
  useExploreStore,
} from '../../features/map-explorer/model/use-explore-store'
import { ComparisonWorkspace } from '../../features/map-explorer/ui/ComparisonWorkspace'
import {
  ExplorerMapViewport,
  type ExplorerMapViewportHandle,
} from '../../features/map-explorer/ui/ExplorerMapViewport'
import { ExplorerTopToolbar } from '../../features/map-explorer/ui/ExplorerTopToolbar'
import { InspectorPanel } from '../../features/map-explorer/ui/InspectorPanel'
import { LayerCatalogSidebar } from '../../features/map-explorer/ui/LayerCatalogSidebar'
import { TemporalLegendBar } from '../../features/map-explorer/ui/TemporalLegendBar'
import { useLayerCatalogQuery } from '../../shared/api/layers'
import { PROJECTION_REGISTRY } from '../../shared/config/geospatial'
import { formatCoordinatePair } from '../../shared/lib/geojson-utils'
import {
  AlertCircle,
  Check,
  Compass,
  Minus,
  Plus,
  X,
} from '../../shared/ui/explorer-icons'

export function MapExplorerWorkspace() {
  useExploreUrlSync()

  const mapViewportRef = useRef<ExplorerMapViewportHandle | null>(null)
  const workspaceRef = useRef<HTMLDivElement | null>(null)

  const projection = useExploreStore((s) => s.projection)
  const basemap = useExploreStore((s) => s.basemap)
  const primaryLayerId = useExploreStore((s) => s.primaryLayerId)
  const layerStates = useExploreStore((s) => s.layerStates)
  const syntheticPreviewEnabled = useExploreStore((s) => s.syntheticPreviewEnabled)
  const selectedDate = useExploreStore((s) => s.selectedDate)

  const showGraticules = useExploreStore((s) => s.showGraticules)
  const showBorders = useExploreStore((s) => s.showBorders)
  const showLabels = useExploreStore((s) => s.showLabels)
  const showRegionBoundaries = useExploreStore((s) => s.showRegionBoundaries)

  const interactionMode = useExploreStore((s) => s.interactionMode)
  const hoverCoordinate = useExploreStore((s) => s.hoverCoordinate)
  const hoveredCountry = useExploreStore((s) => s.hoveredCountry)
  const selectedCountry = useExploreStore((s) => s.selectedCountry)
  const inspectedPoint = useExploreStore((s) => s.inspectedPoint)
  const draftVertices = useExploreStore((s) => s.draftVertices)
  const draftHoverPoint = useExploreStore((s) => s.draftHoverPoint)
  const viewport = useExploreStore((s) => s.viewport)
  const comparisonMode = useExploreStore((s) => s.comparisonMode)
  const isFullscreen = useExploreStore((s) => s.isFullscreen)
  const setIsFullscreen = useExploreStore((s) => s.setIsFullscreen)
  const rendererStatus = useExploreStore((s) => s.rendererStatus)
  const setRendererStatus = useExploreStore((s) => s.setRendererStatus)

  const setHoverCoordinate = useExploreStore((s) => s.setHoverCoordinate)
  const setHoveredCountry = useExploreStore((s) => s.setHoveredCountry)
  const setSelectedCountry = useExploreStore((s) => s.setSelectedCountry)
  const setInspectedPoint = useExploreStore((s) => s.setInspectedPoint)
  const addDraftVertex = useExploreStore((s) => s.addDraftVertex)
  const cancelDraftAoi = useExploreStore((s) => s.cancelDraftAoi)
  const setDraftHoverPoint = useExploreStore((s) => s.setDraftHoverPoint)
  const setViewport = useExploreStore((s) => s.setViewport)
  const leftSidebarOpen = useExploreStore((s) => s.leftSidebarOpen)
  const setLeftSidebarOpen = useExploreStore((s) => s.setLeftSidebarOpen)
  const rightInspectorOpen = useExploreStore((s) => s.rightInspectorOpen)
  const setRightInspectorOpen = useExploreStore((s) => s.setRightInspectorOpen)

  const catalogQuery = useLayerCatalogQuery()
  const layers = catalogQuery.data ?? []
  const activeLayer = layers.find((layer) => layer.id === primaryLayerId) ?? layers[0] ?? null
  const activeLayerControl = activeLayer
    ? resolveLayerControlState(activeLayer, layerStates[activeLayer.id], primaryLayerId)
    : null

  const { aois, selectedAoi, completeDraftAoi } = useAoiWorkspace()
  const selectedAoiId = selectedAoi?.properties.id ?? null

  const renderState = useMemo<MapRenderState>(
    () => ({
      projection,
      basemap,
      selectedDate,
      activeLayer:
        activeLayer && activeLayerControl
          ? {
              layer: activeLayer,
              visible: activeLayerControl.visible,
              opacity: activeLayerControl.opacity,
              minValue: activeLayerControl.minValue,
              maxValue: activeLayerControl.maxValue,
            }
          : null,
      syntheticPreviewEnabled,
      showGraticules,
      showBorders,
      showLabels,
      showRegionBoundaries,
      interactionMode,
      selectedCountry,
      hoveredCountryIso: hoveredCountry?.isoA3 ?? null,
      inspectedPoint,
      aois,
      selectedAoiId,
      draftVertices,
      draftHoverPoint,
      viewport,
    }),
    [
      activeLayer,
      activeLayerControl,
      aois,
      basemap,
      draftHoverPoint,
      draftVertices,
      hoveredCountry?.isoA3,
      inspectedPoint,
      interactionMode,
      projection,
      selectedAoiId,
      selectedCountry,
      selectedDate,
      showBorders,
      showGraticules,
      showLabels,
      showRegionBoundaries,
      syntheticPreviewEnabled,
      viewport,
    ],
  )

  const handleFlyTo = useCallback((center: [number, number], zoom?: number) => {
    mapViewportRef.current?.flyTo(center, zoom)
  }, [])

  const handleResetView = useCallback(() => {
    mapViewportRef.current?.resetView()
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target
      const isEditingInput =
        target instanceof HTMLInputElement ||
        target instanceof HTMLSelectElement ||
        target instanceof HTMLTextAreaElement

      if (event.key === 'Escape') {
        if (interactionMode === 'draw-polygon' || interactionMode === 'draw-rectangle') {
          cancelDraftAoi()
          return
        }
        if (isFullscreen) {
          setIsFullscreen(false)
          return
        }
      }

      if (isEditingInput) return

      if (event.key === '=' || event.key === '+') {
        event.preventDefault()
        mapViewportRef.current?.zoomIn()
      } else if (event.key === '-' || event.key === '_') {
        event.preventDefault()
        mapViewportRef.current?.zoomOut()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [cancelDraftAoi, interactionMode, isFullscreen, setIsFullscreen])

  const isDrawing =
    interactionMode === 'draw-polygon' || interactionMode === 'draw-rectangle'

  return (
    <div
      ref={workspaceRef}
      className={`explorer-workspace ${isFullscreen ? 'is-fullscreen' : ''}`}
      data-projection={projection}
    >
      <ExplorerTopToolbar onFlyTo={handleFlyTo} onResetView={handleResetView} />

      <div className="explorer-workspace__body">
        <LayerCatalogSidebar />

        <div className="explorer-stage-wrap">
          {comparisonMode ? (
            <ComparisonWorkspace />
          ) : (
            <div className="explorer-single-stage">
              <ExplorerMapViewport
                ref={mapViewportRef}
                renderState={renderState}
                onHoverCoordinate={setHoverCoordinate}
                onHoverCountry={setHoveredCountry}
                onSelectCountry={(country) => setSelectedCountry(country)}
                onInspectPoint={(lon, lat) => setInspectedPoint({ lon, lat })}
                onAddDraftVertex={addDraftVertex}
                onCompleteDraftShape={(lon, lat) => {
                  void completeDraftAoi(lon, lat)
                }}
                onUpdateDraftHover={setDraftHoverPoint}
                onViewportChange={setViewport}
                onRendererStatus={setRendererStatus}
                ariaLabel={`Interactive ${PROJECTION_REGISTRY[projection].label} geospatial map`}
              />

              {!rendererStatus.ready && !rendererStatus.error && (
                <div className="explorer-stage-overlay-pill" role="status">
                  Initializing {PROJECTION_REGISTRY[projection].label} renderer...
                </div>
              )}

              {rendererStatus.error && (
                <div className="explorer-stage-error" role="alert">
                  <AlertCircle size={16} aria-hidden="true" />
                  <span>{rendererStatus.error}</span>
                </div>
              )}

              <div className="explorer-stage-hud-tl">
                <span className="explorer-hud-badge">
                  {PROJECTION_REGISTRY[projection].epsgOrName}
                </span>
                {rendererStatus.warning && (
                  <span className="explorer-hud-badge is-warning">
                    {rendererStatus.warning}
                  </span>
                )}
                {hoveredCountry && (
                  <span className="explorer-hud-badge is-highlight">
                    {hoveredCountry.name} ({hoveredCountry.isoA3})
                  </span>
                )}
              </div>

              {isDrawing && (
                <div className="explorer-draw-hud" role="status">
                  <span>
                    {interactionMode === 'draw-polygon'
                      ? `Drawing Polygon (${draftVertices.length} vertices)`
                      : `Drawing Rectangle (${draftVertices.length}/2 corners)`}
                  </span>
                  {interactionMode === 'draw-polygon' && (
                    <button
                      type="button"
                      className="explorer-hud-btn is-primary"
                      disabled={draftVertices.length < 3}
                      onClick={() => void completeDraftAoi()}
                    >
                      <Check size={12} />
                      Finish
                    </button>
                  )}
                  <button
                    type="button"
                    className="explorer-hud-btn"
                    onClick={cancelDraftAoi}
                  >
                    <X size={12} />
                    Cancel
                  </button>
                </div>
              )}

              <div className="explorer-stage-hud-bl">
                <span>
                  {hoverCoordinate
                    ? formatCoordinatePair(hoverCoordinate.lon, hoverCoordinate.lat)
                    : 'WGS 84 · EPSG:4326'}
                </span>
                {rendererStatus.deckGlActive && (
                  <span className="explorer-hud-deck-tag">deck.gl overlay ready</span>
                )}
              </div>

              <div className="explorer-zoom-stack" role="group" aria-label="Map zoom controls">
                <button
                  type="button"
                  className="explorer-zoom-btn"
                  onClick={() => mapViewportRef.current?.zoomIn()}
                  aria-label="Zoom in"
                  title="Zoom in (+)"
                >
                  <Plus size={15} />
                </button>
                <button
                  type="button"
                  className="explorer-zoom-btn"
                  onClick={() => mapViewportRef.current?.zoomOut()}
                  aria-label="Zoom out"
                  title="Zoom out (-)"
                >
                  <Minus size={15} />
                </button>
                <button
                  type="button"
                  className="explorer-zoom-btn"
                  onClick={handleResetView}
                  aria-label="Reset camera extent"
                  title="Reset camera"
                >
                  <Compass size={15} />
                </button>
              </div>
            </div>
          )}

          <TemporalLegendBar />
        </div>

        <InspectorPanel />

        {(leftSidebarOpen || rightInspectorOpen) && (
          <div
            className="explorer-mobile-backdrop"
            onClick={() => {
              setLeftSidebarOpen(false)
              setRightInspectorOpen(false)
            }}
            aria-hidden="true"
          />
        )}
      </div>
    </div>
  )
}
