import {
  LIVE_GIBS_LAYERS,
  findLiveLayer,
  type LiveDomain,
} from '../../../shared/config/live-environment'
import { useExploreStore } from '../../map-explorer/model/use-explore-store'

const DOMAINS: readonly { id: LiveDomain; label: string }[] = [
  { id: 'vegetation', label: 'Vegetation' },
  { id: 'temperature', label: 'Temperature' },
  { id: 'water', label: 'Precipitation & Water' },
  { id: 'soil', label: 'Soil Moisture' },
  { id: 'cryosphere', label: 'Cryosphere' },
]

export function LiveLayerCatalog() {
  const gibsLayerId = useExploreStore((s) => s.gibsLayerId)
  const gibsDate = useExploreStore((s) => s.gibsDate)
  const setGibsLayer = useExploreStore((s) => s.setGibsLayer)
  const setGibsDate = useExploreStore((s) => s.setGibsDate)
  const setRightInspectorOpen = useExploreStore((s) => s.setRightInspectorOpen)
  const setInspectorTab = useExploreStore((s) => s.setInspectorTab)
  const activeLayer = findLiveLayer(gibsLayerId)

  return (
    <section className="explorer-sidebar-section live-layer-section" aria-label="Live NASA layers">
      <div className="live-layer-head">
        <div>
          <h3 className="explorer-group-heading">Live NASA Layers</h3>
          <p className="explorer-panel-subtitle">Direct from NASA GIBS · no backend</p>
        </div>
        <span className="explorer-status-pill is-connected">GIBS</span>
      </div>

      <p className="explorer-muted-copy live-layer-intro">
        Global pre-rendered environmental visualizations. These tiles are for display only and
        are never used as numerical scientific values.
      </p>

      <div className="live-layer-groups">
        {DOMAINS.map((domain) => {
          const layers = LIVE_GIBS_LAYERS.filter((layer) => layer.domain === domain.id)
          if (layers.length === 0) return null
          return (
            <div key={domain.id} className="live-layer-group">
              <span className="live-layer-group__label">{domain.label}</span>
              <div className="live-layer-grid">
                {layers.map((layer) => {
                  const isActive = layer.id === gibsLayerId
                  return (
                    <button
                      key={layer.id}
                      type="button"
                      className={`live-layer-card ${isActive ? 'is-active' : ''}`}
                      onClick={() => {
                        setGibsLayer(layer.id)
                        setRightInspectorOpen(true)
                        setInspectorTab('live')
                      }}
                      aria-pressed={isActive}
                    >
                      <span className="live-layer-card__name">{layer.shortName}</span>
                      <span className="live-layer-card__meta">
                        {layer.nativeResolution} · {layer.temporalCadence} · {layer.unit}
                      </span>
                      <span className="live-layer-card__note">
                        {isActive ? 'Displayed on map' : 'Visualization only'}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      {activeLayer ? (
        <div className="live-layer-date">
          <label htmlFor="live-layer-date">
            <span>Observation date</span>
            <input
              id="live-layer-date"
              type="date"
              value={gibsDate}
              onChange={(e) => {
                if (e.target.value) setGibsDate(e.target.value)
              }}
            />
          </label>
          <button
            type="button"
            className="explorer-action-btn"
            onClick={() => setGibsDate(activeLayer.defaultObservationDate)}
          >
            Latest available
          </button>
        </div>
      ) : null}

      <p className="explorer-resolution-note">
        Provider: NASA EOSDIS GIBS. Calculation availability is reported separately in the Live
        Data inspector. Numerical NDVI uses MOD13Q1 COG windows from Planetary Computer; point
        meteorology uses NASA POWER.
      </p>
    </section>
  )
}
