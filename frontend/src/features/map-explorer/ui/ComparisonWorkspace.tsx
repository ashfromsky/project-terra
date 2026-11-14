import { useCallback, useMemo, useRef } from 'react'
import {
  ENVIRONMENTAL_LAYER_CATALOG,
  getLayerDefinition,
} from '../../../entities/layer/model/layer-catalog'
import type { MapRenderState } from '../../../entities/map/model/map-renderer'
import { BASEMAP_LIST } from '../../../shared/config/geospatial'
import type { BasemapId, MapViewportState } from '../../../shared/types/geospatial'
import { Info, Link2, Link2Off } from '../../../shared/ui/explorer-icons'
import { useExploreStore } from '../model/use-explore-store'
import {
  ExplorerMapViewport,
  type ExplorerMapViewportHandle,
} from './ExplorerMapViewport'

export function ComparisonWorkspace() {
  const projection = useExploreStore((s) => s.projection)
  const syncCameras = useExploreStore((s) => s.syncCameras)
  const setSyncCameras = useExploreStore((s) => s.setSyncCameras)
  const comparisonLeft = useExploreStore((s) => s.comparisonLeft)
  const comparisonRight = useExploreStore((s) => s.comparisonRight)
  const setComparisonLeft = useExploreStore((s) => s.setComparisonLeft)
  const setComparisonRight = useExploreStore((s) => s.setComparisonRight)

  const syntheticPreviewEnabled = useExploreStore((s) => s.syntheticPreviewEnabled)
  const showGraticules = useExploreStore((s) => s.showGraticules)
  const showBorders = useExploreStore((s) => s.showBorders)
  const showLabels = useExploreStore((s) => s.showLabels)
  const showRegionBoundaries = useExploreStore((s) => s.showRegionBoundaries)
  const interactionMode = useExploreStore((s) => s.interactionMode)
  const selectedCountry = useExploreStore((s) => s.selectedCountry)
  const hoveredCountry = useExploreStore((s) => s.hoveredCountry)
  const inspectedPoint = useExploreStore((s) => s.inspectedPoint)
  const aois = useExploreStore((s) => s.aois)
  const selectedAoiId = useExploreStore((s) => s.selectedAoiId)
  const draftVertices = useExploreStore((s) => s.draftVertices)
  const draftHoverPoint = useExploreStore((s) => s.draftHoverPoint)
  const viewport = useExploreStore((s) => s.viewport)
  const setViewport = useExploreStore((s) => s.setViewport)
  const setHoverCoordinate = useExploreStore((s) => s.setHoverCoordinate)
  const setHoveredCountry = useExploreStore((s) => s.setHoveredCountry)
  const setSelectedCountry = useExploreStore((s) => s.setSelectedCountry)
  const setInspectedPoint = useExploreStore((s) => s.setInspectedPoint)
  const addDraftVertex = useExploreStore((s) => s.addDraftVertex)
  const completeDraftAoi = useExploreStore((s) => s.completeDraftAoi)
  const setDraftHoverPoint = useExploreStore((s) => s.setDraftHoverPoint)

  const leftViewportRef = useRef<ExplorerMapViewportHandle | null>(null)
  const rightViewportRef = useRef<ExplorerMapViewportHandle | null>(null)
  const isSyncingRef = useRef(false)

  const leftLayer = getLayerDefinition(comparisonLeft.layerId)
  const rightLayer = getLayerDefinition(comparisonRight.layerId)

  const leftRenderState = useMemo<MapRenderState>(
    () => ({
      projection,
      basemap: comparisonLeft.basemap,
      selectedDate: comparisonLeft.date,
      activeLayer: {
        layer: leftLayer,
        visible: true,
        opacity: comparisonLeft.opacity,
        minValue: leftLayer.valueRange.defaultMin,
        maxValue: leftLayer.valueRange.defaultMax,
      },
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
      aois,
      comparisonLeft.basemap,
      comparisonLeft.date,
      comparisonLeft.opacity,
      draftHoverPoint,
      draftVertices,
      hoveredCountry?.isoA3,
      inspectedPoint,
      interactionMode,
      leftLayer,
      projection,
      selectedAoiId,
      selectedCountry,
      showBorders,
      showGraticules,
      showLabels,
      showRegionBoundaries,
      syntheticPreviewEnabled,
      viewport,
    ],
  )

  const rightRenderState = useMemo<MapRenderState>(
    () => ({
      projection,
      basemap: comparisonRight.basemap,
      selectedDate: comparisonRight.date,
      activeLayer: {
        layer: rightLayer,
        visible: true,
        opacity: comparisonRight.opacity,
        minValue: rightLayer.valueRange.defaultMin,
        maxValue: rightLayer.valueRange.defaultMax,
      },
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
      aois,
      comparisonRight.basemap,
      comparisonRight.date,
      comparisonRight.opacity,
      draftHoverPoint,
      draftVertices,
      hoveredCountry?.isoA3,
      inspectedPoint,
      interactionMode,
      projection,
      rightLayer,
      selectedAoiId,
      selectedCountry,
      showBorders,
      showGraticules,
      showLabels,
      showRegionBoundaries,
      syntheticPreviewEnabled,
      viewport,
    ],
  )

  const handlePaneViewportChange = useCallback(
    (source: 'left' | 'right', nextViewport: MapViewportState) => {
      setViewport(nextViewport)
      if (!syncCameras || isSyncingRef.current) return
      isSyncingRef.current = true
      if (source === 'left') {
        rightViewportRef.current?.setViewport(nextViewport, false)
      } else {
        leftViewportRef.current?.setViewport(nextViewport, false)
      }
      window.setTimeout(() => {
        isSyncingRef.current = false
      }, 40)
    },
    [setViewport, syncCameras],
  )

  const regionA = aois.find((a) => a.properties.role === 'regionA')
  const regionB = aois.find((a) => a.properties.role === 'regionB')

  return (
    <div className="explorer-comparison">
      <div className="explorer-comparison__bar">
        <div className="explorer-comparison__bar-left">
          <button
            type="button"
            className={`explorer-icon-btn ${syncCameras ? 'is-active' : ''}`}
            onClick={() => setSyncCameras(!syncCameras)}
            aria-pressed={syncCameras}
          >
            {syncCameras ? <Link2 size={14} /> : <Link2Off size={14} />}
            <span>{syncCameras ? 'Cameras synced' : 'Independent cameras'}</span>
          </button>

          <span className="explorer-region-chip is-region-a">
            Region A: {regionA ? regionA.properties.name : 'Unassigned'}
          </span>
          <span className="explorer-region-chip is-region-b">
            Region B: {regionB ? regionB.properties.name : 'Unassigned'}
          </span>
        </div>

        <div className="explorer-comparison__bar-right" title="Scientific integrity boundary">
          <Info size={13} aria-hidden="true" />
          <span>
            Swipe &amp; Pixel Difference Maps require connected backend observations; no synthetic
            delta is computed.
          </span>
        </div>
      </div>

      <div className="explorer-comparison__grid">
        <section className="explorer-comparison__pane is-pane-a" aria-label="Comparison Pane A">
          <div className="explorer-comparison__pane-head">
            <span className="explorer-pane-badge is-region-a">Pane A</span>
            <select
              className="explorer-mini-select"
              value={comparisonLeft.layerId}
              onChange={(e) => setComparisonLeft({ layerId: e.target.value })}
              aria-label="Pane A environmental layer"
            >
              {ENVIRONMENTAL_LAYER_CATALOG.map((layer) => (
                <option key={layer.id} value={layer.id}>
                  {layer.name}
                </option>
              ))}
            </select>
            <input
              type="date"
              className="explorer-mini-date"
              value={comparisonLeft.date}
              onChange={(e) => {
                if (e.target.value) setComparisonLeft({ date: e.target.value })
              }}
              aria-label="Pane A date"
            />
            <select
              className="explorer-mini-select"
              value={comparisonLeft.basemap}
              onChange={(e) =>
                setComparisonLeft({ basemap: e.target.value as BasemapId })
              }
              aria-label="Pane A basemap"
            >
              {BASEMAP_LIST.map((bm) => (
                <option
                  key={bm.id}
                  value={bm.id}
                  disabled={projection === 'equal-earth' && !bm.supportsEqualEarth}
                >
                  {bm.shortName}
                </option>
              ))}
            </select>
          </div>

          <div className="explorer-comparison__viewport">
            <ExplorerMapViewport
              ref={leftViewportRef}
              renderState={leftRenderState}
              onHoverCoordinate={setHoverCoordinate}
              onHoverCountry={setHoveredCountry}
              onSelectCountry={(country) => setSelectedCountry(country)}
              onInspectPoint={(lon, lat) => setInspectedPoint({ lon, lat })}
              onAddDraftVertex={addDraftVertex}
              onCompleteDraftShape={completeDraftAoi}
              onUpdateDraftHover={setDraftHoverPoint}
              onViewportChange={(vp) => handlePaneViewportChange('left', vp)}
              ariaLabel="Comparison Left Map Pane"
            />
          </div>

          <div className="explorer-comparison__legend">
            <span>
              {leftLayer.shortName} ({leftLayer.unit})
            </span>
            <div
              className="explorer-legend-gradient"
              style={{ background: leftLayer.legend.gradientCss }}
            />
            <span>
              {leftLayer.legend.minLabel} → {leftLayer.legend.maxLabel}
            </span>
          </div>
        </section>

        <section className="explorer-comparison__pane is-pane-b" aria-label="Comparison Pane B">
          <div className="explorer-comparison__pane-head">
            <span className="explorer-pane-badge is-region-b">Pane B</span>
            <select
              className="explorer-mini-select"
              value={comparisonRight.layerId}
              onChange={(e) => setComparisonRight({ layerId: e.target.value })}
              aria-label="Pane B environmental layer"
            >
              {ENVIRONMENTAL_LAYER_CATALOG.map((layer) => (
                <option key={layer.id} value={layer.id}>
                  {layer.name}
                </option>
              ))}
            </select>
            <input
              type="date"
              className="explorer-mini-date"
              value={comparisonRight.date}
              onChange={(e) => {
                if (e.target.value) setComparisonRight({ date: e.target.value })
              }}
              aria-label="Pane B date"
            />
            <select
              className="explorer-mini-select"
              value={comparisonRight.basemap}
              onChange={(e) =>
                setComparisonRight({ basemap: e.target.value as BasemapId })
              }
              aria-label="Pane B basemap"
            >
              {BASEMAP_LIST.map((bm) => (
                <option
                  key={bm.id}
                  value={bm.id}
                  disabled={projection === 'equal-earth' && !bm.supportsEqualEarth}
                >
                  {bm.shortName}
                </option>
              ))}
            </select>
          </div>

          <div className="explorer-comparison__viewport">
            <ExplorerMapViewport
              ref={rightViewportRef}
              renderState={rightRenderState}
              onHoverCoordinate={setHoverCoordinate}
              onHoverCountry={setHoveredCountry}
              onSelectCountry={(country) => setSelectedCountry(country)}
              onInspectPoint={(lon, lat) => setInspectedPoint({ lon, lat })}
              onAddDraftVertex={addDraftVertex}
              onCompleteDraftShape={completeDraftAoi}
              onUpdateDraftHover={setDraftHoverPoint}
              onViewportChange={(vp) => handlePaneViewportChange('right', vp)}
              ariaLabel="Comparison Right Map Pane"
            />
          </div>

          <div className="explorer-comparison__legend">
            <span>
              {rightLayer.shortName} ({rightLayer.unit})
            </span>
            <div
              className="explorer-legend-gradient"
              style={{ background: rightLayer.legend.gradientCss }}
            />
            <span>
              {rightLayer.legend.minLabel} → {rightLayer.legend.maxLabel}
            </span>
          </div>
        </section>
      </div>
    </div>
  )
}
