import { figmaAssets } from '../../../shared/config/assets'
import {
  useUiStore,
  type MapLayerVisibility,
  type MapToolId,
} from '../../../shared/store/ui-store'
import { CARTOGRAPHIC_PROJECTION_SPEC } from '../config/map-style'

export interface MapControlsToolbarProps {
  onZoomIn: () => void
  onZoomOut: () => void
  onResetWorldView: () => void
  onFullscreen: () => void
  currentZoom: number
}

const LAYER_TOGGLE_ITEMS: ReadonlyArray<{
  key: keyof MapLayerVisibility
  label: string
  engineBadge: string
}> = [
  {
    key: 'thematicOverlay',
    label: 'Thematic choropleth field',
    engineBadge: 'MapLibre',
  },
  {
    key: 'anomalyGrid',
    label: 'Sub-basin anomaly grid',
    engineBadge: 'deck.gl',
  },
  {
    key: 'regionBoundaries',
    label: 'Region AOI boundaries',
    engineBadge: 'deck.gl',
  },
  {
    key: 'anomalyHotspots',
    label: 'Anomaly hotspot markers',
    engineBadge: 'deck.gl',
  },
  {
    key: 'countryBorders',
    label: 'Natural Earth borders',
    engineBadge: '1:110m',
  },
  {
    key: 'graticules',
    label: 'Graticule lines & equator',
    engineBadge: 'WGS 84',
  },
  {
    key: 'countryLabels',
    label: 'Continent & country labels',
    engineBadge: 'Labels',
  },
]

function getActiveToolOffsetY(tool: MapToolId): number {
  switch (tool) {
    case 'layers':
      return 0
    case 'region-selection':
      return 42
    case 'locate':
      return 84
    case 'zoom-in':
      return 126
    case 'zoom-out':
      return 168
    case 'fullscreen':
      return 210
  }
}

export function MapControlsToolbar({
  onZoomIn,
  onZoomOut,
  onResetWorldView,
  onFullscreen,
  currentZoom,
}: MapControlsToolbarProps) {
  const activeMapTool = useUiStore((state) => state.activeMapTool)
  const setActiveMapTool = useUiStore((state) => state.setActiveMapTool)
  const layerVisibility = useUiStore((state) => state.layerVisibility)
  const toggleLayerVisibility = useUiStore(
    (state) => state.toggleLayerVisibility,
  )
  const layerPanelOpen = useUiStore((state) => state.layerPanelOpen)
  const toggleLayerPanel = useUiStore((state) => state.toggleLayerPanel)
  const setLayerPanelOpen = useUiStore((state) => state.setLayerPanelOpen)

  return (
    <>
      <div
        className="earth-observatory__map-tools"
        data-node-id="5:242"
        role="toolbar"
        aria-label="Map tools"
      >
        <div
          className="earth-observatory__tool-active-bg"
          data-node-id="5:243"
          style={{
            transform: `translateY(${getActiveToolOffsetY(activeMapTool)}px)`,
          }}
        />
        <button
          type="button"
          className="earth-observatory__tool-btn"
          style={{ top: '14px' }}
          data-node-id="5:244"
          aria-label="Map layers"
          aria-expanded={layerPanelOpen}
          aria-pressed={activeMapTool === 'layers' || layerPanelOpen}
          onClick={() => {
            setActiveMapTool('layers')
            toggleLayerPanel()
          }}
        >
          <img src={figmaAssets.layers} alt="" />
        </button>
        <button
          type="button"
          className="earth-observatory__tool-btn"
          style={{ top: '56px' }}
          data-node-id="5:246"
          aria-label="Region selection"
          aria-pressed={activeMapTool === 'region-selection'}
          onClick={() => {
            setActiveMapTool('region-selection')
            setLayerPanelOpen(false)
          }}
        >
          <img src={figmaAssets.regionSelection} alt="" />
        </button>
        <button
          type="button"
          className="earth-observatory__tool-btn"
          style={{ top: '98px' }}
          data-node-id="5:248"
          aria-label="Reset map center"
          aria-pressed={activeMapTool === 'locate'}
          onClick={() => {
            setActiveMapTool('locate')
            setLayerPanelOpen(false)
            onResetWorldView()
          }}
        >
          <img src={figmaAssets.locate} alt="" />
        </button>
        <button
          type="button"
          className="earth-observatory__tool-btn"
          style={{ top: '140px' }}
          data-node-id="5:252"
          aria-label="Zoom in"
          onClick={() => {
            setActiveMapTool('zoom-in')
            onZoomIn()
          }}
        >
          <img src={figmaAssets.zoomIn} alt="" />
        </button>
        <button
          type="button"
          className="earth-observatory__tool-btn"
          style={{ top: '182px' }}
          data-node-id="5:254"
          aria-label="Zoom out"
          onClick={() => {
            setActiveMapTool('zoom-out')
            onZoomOut()
          }}
        >
          <img src={figmaAssets.zoomOut} alt="" />
        </button>
        <button
          type="button"
          className="earth-observatory__tool-btn"
          style={{ top: '224px' }}
          data-node-id="5:256"
          aria-label="Open full map explorer"
          onClick={() => {
            setActiveMapTool('fullscreen')
            setLayerPanelOpen(false)
            onFullscreen()
          }}
        >
          <img src={figmaAssets.fullscreen} alt="" />
        </button>
      </div>

      {layerPanelOpen && (
        <div
          className="world-map__layer-popover"
          role="dialog"
          aria-label="Map layer visibility controls"
        >
          <div className="world-map__layer-popover-header">
            <span className="world-map__layer-popover-title">
              CARTOGRAPHY & OVERLAYS
            </span>
            <span className="world-map__layer-popover-zoom">
              z{currentZoom.toFixed(1)}
            </span>
          </div>
          <ul className="world-map__layer-list">
            {LAYER_TOGGLE_ITEMS.map((item) => {
              const checked = layerVisibility[item.key]
              return (
                <li key={item.key} className="world-map__layer-item">
                  <label className="world-map__layer-label">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleLayerVisibility(item.key)}
                      className="world-map__layer-checkbox"
                    />
                    <span className="world-map__layer-text">{item.label}</span>
                    <span className="world-map__layer-badge">
                      {item.engineBadge}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
          <div className="world-map__layer-popover-footer">
            <p className="world-map__layer-meta">
              {CARTOGRAPHIC_PROJECTION_SPEC.datasetName}
            </p>
            <p className="world-map__layer-meta">
              {CARTOGRAPHIC_PROJECTION_SPEC.renderedProjection} · Synthetic demo
              overlays
            </p>
          </div>
        </div>
      )}
    </>
  )
}
