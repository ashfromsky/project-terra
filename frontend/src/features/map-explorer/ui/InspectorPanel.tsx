import { useLayerCatalogQuery } from '../../../shared/api/layers'
import { PROJECTION_REGISTRY } from '../../../shared/config/geospatial'
import { formatCoordinatePair } from '../../../shared/lib/geojson-utils'
import { Info, X } from '../../../shared/ui/explorer-icons'
import { useAoiWorkspace } from '../model/use-aoi-workspace'
import { useExploreStore } from '../model/use-explore-store'
import { LiveSciencePanel } from '../../live-environment/ui/LiveSciencePanel'
import { InspectorAoiTab } from './InspectorAoiTab'
import { InspectorFeatureTab } from './InspectorFeatureTab'
import { InspectorPointTab } from './InspectorPointTab'

export function InspectorPanel() {
  const rightInspectorOpen = useExploreStore((s) => s.rightInspectorOpen)
  const setRightInspectorOpen = useExploreStore((s) => s.setRightInspectorOpen)
  const tab = useExploreStore((s) => s.inspectorTab)
  const setTab = useExploreStore((s) => s.setInspectorTab)
  const projection = useExploreStore((s) => s.projection)
  const primaryLayerId = useExploreStore((s) => s.primaryLayerId)
  const hoverCoordinate = useExploreStore((s) => s.hoverCoordinate)

  const catalogQuery = useLayerCatalogQuery()
  const layers = catalogQuery.data ?? []
  const activeLayer = layers.find((l) => l.id === primaryLayerId) ?? layers[0] ?? null
  const { aois } = useAoiWorkspace()

  if (!rightInspectorOpen) {
    return null
  }

  return (
    <aside
      className="explorer-sidebar explorer-sidebar--right"
      aria-label="Geographic coordinates and AOI inspector"
    >
      <div className="explorer-panel-header">
        <div>
          <h2 className="explorer-panel-title">Geographic Inspector</h2>
          <p className="explorer-panel-subtitle">{PROJECTION_REGISTRY[projection].epsgOrName}</p>
        </div>
        <button
          type="button"
          className="explorer-panel-close"
          onClick={() => setRightInspectorOpen(false)}
          aria-label="Collapse inspector sidebar"
        >
          <X size={15} />
        </button>
      </div>

      <div className="explorer-coord-readout">
        <span className="explorer-coord-readout__label">Cursor WGS 84</span>
        <span className="explorer-coord-readout__value">
          {hoverCoordinate
            ? formatCoordinatePair(hoverCoordinate.lon, hoverCoordinate.lat)
            : 'Move pointer over map'}
        </span>
      </div>

      {projection === 'mercator' && (
        <div className="explorer-inline-warning">
          <Info size={13} aria-hidden="true" />
          <span>
            Web Mercator (EPSG:3857) is visualization-only; distance and area measurements require
            projected/geodesic backend services.
          </span>
        </div>
      )}

      <div className="explorer-tabs" role="tablist" aria-label="Inspector sections">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'point'}
          className={`explorer-tabs__btn ${tab === 'point' ? 'is-active' : ''}`}
          onClick={() => setTab('point')}
        >
          Point
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'feature'}
          className={`explorer-tabs__btn ${tab === 'feature' ? 'is-active' : ''}`}
          onClick={() => setTab('feature')}
        >
          Feature
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'aoi'}
          className={`explorer-tabs__btn ${tab === 'aoi' ? 'is-active' : ''}`}
          onClick={() => setTab('aoi')}
        >
          AOI ({aois.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'live'}
          className={`explorer-tabs__btn ${tab === 'live' ? 'is-active' : ''}`}
          onClick={() => setTab('live')}
        >
          Live
        </button>
      </div>

      <div className="explorer-sidebar__scroll">
        {tab === 'point' && (
          <InspectorPointTab
            activeLayer={activeLayer}
            catalogLoading={catalogQuery.isPending}
          />
        )}
        {tab === 'feature' && <InspectorFeatureTab />}
        {tab === 'aoi' && <InspectorAoiTab />}
        {tab === 'live' && <LiveSciencePanel />}
      </div>
    </aside>
  )
}
