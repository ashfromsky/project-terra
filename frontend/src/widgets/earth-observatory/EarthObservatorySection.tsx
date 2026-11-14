import { useState } from 'react'
import { useNavigate } from 'react-router'
import { figmaAssets } from '../../shared/config/assets'
import { APP_ROUTES } from '../../shared/config/routes'
import {
  useUiStore,
  type RegionOption,
  type VariableOption,
} from '../../shared/store/ui-store'

const VARIABLE_OPTIONS: readonly VariableOption[] = [
  'Land surface temperature',
  'Vegetation index (NDVI)',
  'Enhanced vegetation (EVI)',
  'Precipitation anomaly',
]

const REGION_OPTIONS: readonly RegionOption[] = [
  'Global land',
  'Amazon basin',
  'Sahel belt',
  'Siberian boreal',
  'Mediterranean basin',
  'Australian outback',
]

interface HotspotMarker {
  id: string
  regionName: RegionOption
  left: number
  top: number
  centerLeft: number
  centerTop: number
  trendLabel: string
  significanceLabel: string
  tone: 'coral' | 'teal'
}

const HOTSPOT_MARKERS: readonly HotspotMarker[] = [
  {
    id: 'north-america',
    regionName: 'Global land',
    left: 554,
    top: 191,
    centerLeft: 564,
    centerTop: 201,
    trendLabel: '+0.34°C / decade',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
  },
  {
    id: 'sahel',
    regionName: 'Sahel belt',
    left: 870,
    top: 262,
    centerLeft: 880,
    centerTop: 272,
    trendLabel: '+0.38°C / decade',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
  },
  {
    id: 'siberia',
    regionName: 'Siberian boreal',
    left: 1065,
    top: 157,
    centerLeft: 1075,
    centerTop: 167,
    trendLabel: '+0.46°C / decade',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
  },
  {
    id: 'se-asia',
    regionName: 'Global land',
    left: 1116,
    top: 268,
    centerLeft: 1126,
    centerTop: 278,
    trendLabel: '+0.14°C / decade',
    significanceLabel: 'p = 0.012 · Significant',
    tone: 'teal',
  },
  {
    id: 'australia',
    regionName: 'Australian outback',
    left: 1224,
    top: 323,
    centerLeft: 1234,
    centerTop: 333,
    trendLabel: '+0.29°C / decade',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
  },
  {
    id: 'amazon',
    regionName: 'Amazon basin',
    left: 622,
    top: 288,
    centerLeft: 632,
    centerTop: 298,
    trendLabel: '+0.31°C / decade',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'teal',
  },
]

const GEOGRAPHIC_LABELS = [
  { text: 'NORTH AMERICA', left: 460, top: 206, nodeId: '5:209' },
  { text: 'SOUTH AMERICA', left: 614, top: 369, nodeId: '5:210' },
  { text: 'EUROPE', left: 833, top: 188, nodeId: '5:211' },
  { text: 'AFRICA', left: 837, top: 303, nodeId: '5:212' },
  { text: 'ASIA', left: 1081, top: 206, nodeId: '5:213' },
  { text: 'AUSTRALIA', left: 1208, top: 377, nodeId: '5:214' },
  { text: 'PACIFIC OCEAN', left: 370, top: 352, nodeId: '5:215' },
  { text: 'ATLANTIC OCEAN', left: 710, top: 291, nodeId: '5:216' },
  { text: 'INDIAN OCEAN', left: 1026, top: 388, nodeId: '5:217' },
] as const

export function EarthObservatorySection() {
  const navigate = useNavigate()
  const panelOpen = useUiStore((state) => state.panelOpen)
  const togglePanel = useUiStore((state) => state.togglePanel)
  const selectedVariable = useUiStore((state) => state.selectedVariable)
  const setSelectedVariable = useUiStore((state) => state.setSelectedVariable)
  const selectedRegion = useUiStore((state) => state.selectedRegion)
  const setSelectedRegion = useUiStore((state) => state.setSelectedRegion)
  const activeMapTool = useUiStore((state) => state.activeMapTool)
  const setActiveMapTool = useUiStore((state) => state.setActiveMapTool)
  const selectedHotspotId = useUiStore((state) => state.selectedHotspotId)
  const setSelectedHotspotId = useUiStore((state) => state.setSelectedHotspotId)

  const [variableMenuOpen, setVariableMenuOpen] = useState(false)
  const [regionMenuOpen, setRegionMenuOpen] = useState(false)
  const [mapScale, setMapScale] = useState(1)

  const activeHotspot =
    HOTSPOT_MARKERS.find((item) => item.id === selectedHotspotId) ??
    HOTSPOT_MARKERS[5]

  const calloutTitle =
    activeHotspot.id === 'amazon'
      ? 'Amazon basin'
      : activeHotspot.regionName === 'Global land'
        ? 'Selected anomaly zone'
        : activeHotspot.regionName

  return (
    <section
      className="earth-observatory"
      data-node-id="5:112"
      aria-label="Earth observatory"
    >
      <div className="earth-observatory__canvas">
        <div
          className="earth-observatory__world-map"
          data-node-id="5:185"
          style={
            mapScale !== 1
              ? { transform: `scale(${mapScale})`, transformOrigin: 'center center' }
              : undefined
          }
        >
          <div className="earth-observatory__grid" data-node-id="5:186">
            <img
              src={figmaAssets.geographicGrid}
              alt=""
              className="earth-observatory__map-img"
            />
          </div>
          <div className="earth-observatory__trend-field" data-node-id="5:207">
            <img
              src={figmaAssets.landSurfaceTrendField}
              alt="Global land surface temperature trend field"
              className="earth-observatory__map-img"
            />
          </div>
        </div>

        {panelOpen ? (
          <aside
            className="dataset-explorer"
            data-node-id="5:146"
            aria-label="Dataset explorer"
          >
            <p className="dataset-explorer__overline" data-node-id="5:147">
              DATA EXPLORER
            </p>
            <button
              type="button"
              className="dataset-explorer__collapse"
              data-node-id="5:148"
              aria-label="Collapse data explorer panel"
              onClick={togglePanel}
            >
              <img src={figmaAssets.collapsePanel} alt="" />
            </button>
            <div className="dataset-explorer__divider dataset-explorer__divider--top" data-node-id="5:150" />

            <p className="dataset-explorer__section-title" data-node-id="5:151">
              NASA datasets
            </p>

            <button
              type="button"
              className="dataset-explorer__dataset-card"
              data-node-id="5:152"
              onClick={() => navigate(APP_ROUTES.dataSources)}
            >
              <span className="dataset-explorer__dataset-icon" data-node-id="5:153">
                <img src={figmaAssets.dataset} alt="" />
              </span>
              <span className="dataset-explorer__dataset-title" data-node-id="5:156">
                MODIS Terra
              </span>
              <span className="dataset-explorer__dataset-meta" data-node-id="5:157">
                MOD11C3 · Monthly · 0.05°
              </span>
              <span className="dataset-explorer__dataset-check" data-node-id="5:158">
                <img src={figmaAssets.datasetSelected} alt="" />
              </span>
            </button>

            <button
              type="button"
              className="dataset-explorer__compare-link"
              data-node-id="5:160"
              onClick={() => navigate(APP_ROUTES.comparativeAnalysis)}
            >
              +  Compare with another dataset
            </button>

            <div className="dataset-explorer__divider dataset-explorer__divider--mid" data-node-id="5:161" />

            <p className="dataset-explorer__label dataset-explorer__label--variable" data-node-id="5:162">
              VARIABLE
            </p>

            <div className="dataset-explorer__selector-wrap dataset-explorer__selector-wrap--variable">
              <button
                type="button"
                className="dataset-explorer__selector"
                data-node-id="5:163"
                aria-expanded={variableMenuOpen}
                onClick={() => {
                  setVariableMenuOpen((open) => !open)
                  setRegionMenuOpen(false)
                }}
              >
                <span className="dataset-explorer__selector-icon--temp" data-node-id="5:164">
                  <img src={figmaAssets.temperature} alt="" />
                </span>
                <span className="dataset-explorer__selector-text--temp" data-node-id="5:166">
                  {selectedVariable}
                </span>
                <span className="dataset-explorer__selector-chevron" data-node-id="5:167">
                  <img src={figmaAssets.chooseChevron} alt="" />
                </span>
              </button>
              {variableMenuOpen && (
                <ul className="dataset-explorer__menu" role="listbox" aria-label="Select variable">
                  {VARIABLE_OPTIONS.map((option) => (
                    <li key={option}>
                      <button
                        type="button"
                        className={`dataset-explorer__menu-item ${
                          option === selectedVariable
                            ? 'dataset-explorer__menu-item--active'
                            : ''
                        }`}
                        onClick={() => {
                          setSelectedVariable(option)
                          setVariableMenuOpen(false)
                        }}
                      >
                        {option}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <p className="dataset-explorer__label dataset-explorer__label--region" data-node-id="5:169">
              GEOGRAPHIC REGION
            </p>

            <div className="dataset-explorer__selector-wrap dataset-explorer__selector-wrap--region">
              <button
                type="button"
                className="dataset-explorer__selector"
                data-node-id="5:170"
                aria-expanded={regionMenuOpen}
                onClick={() => {
                  setRegionMenuOpen((open) => !open)
                  setVariableMenuOpen(false)
                }}
              >
                <span className="dataset-explorer__selector-icon--region" data-node-id="5:171">
                  <img src={figmaAssets.regionBoundaries} alt="" />
                </span>
                <span className="dataset-explorer__selector-text--region" data-node-id="5:173">
                  {selectedRegion}
                </span>
                <span className="dataset-explorer__selector-chevron" data-node-id="5:174">
                  <img src={figmaAssets.chooseChevron} alt="" />
                </span>
              </button>
              {regionMenuOpen && (
                <ul className="dataset-explorer__menu" role="listbox" aria-label="Select geographic region">
                  {REGION_OPTIONS.map((option) => (
                    <li key={option}>
                      <button
                        type="button"
                        className={`dataset-explorer__menu-item ${
                          option === selectedRegion
                            ? 'dataset-explorer__menu-item--active'
                            : ''
                        }`}
                        onClick={() => {
                          setSelectedRegion(option)
                          if (option === 'Amazon basin') {
                            setSelectedHotspotId('amazon')
                          }
                          setRegionMenuOpen(false)
                        }}
                      >
                        {option}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <button
              type="button"
              className="dataset-explorer__draw-link"
              data-node-id="5:176"
              onClick={() => {
                setActiveMapTool('region-selection')
                navigate(APP_ROUTES.explore)
              }}
            >
              <span>Draw a region</span>
            </button>
            <button
              type="button"
              className="dataset-explorer__draw-icon"
              data-node-id="5:177"
              aria-label="Draw custom region on map"
              onClick={() => {
                setActiveMapTool('region-selection')
                navigate(APP_ROUTES.explore)
              }}
            >
              <img src={figmaAssets.drawRegion} alt="" />
            </button>

            <div className="dataset-explorer__divider dataset-explorer__divider--bottom" data-node-id="5:179" />

            <p className="dataset-explorer__label dataset-explorer__label--method" data-node-id="5:180">
              ANALYSIS METHOD
            </p>
            <p className="dataset-explorer__method-value" data-node-id="5:181">
              Ordinary least squares
            </p>
            <div className="dataset-explorer__ci-pill" data-node-id="5:182" />
            <p className="dataset-explorer__ci-text" data-node-id="5:183">
              95% CI
            </p>
            <p className="dataset-explorer__footnote" data-node-id="5:184">
              Quality-screened · Daytime observations
            </p>
          </aside>
        ) : (
          <button
            type="button"
            className="dataset-explorer-collapsed-btn"
            onClick={togglePanel}
            aria-label="Expand data explorer panel"
          >
            <span>DATA EXPLORER</span>
            <span aria-hidden="true">›</span>
          </button>
        )}

        {GEOGRAPHIC_LABELS.map((item) => (
          <p
            key={item.text}
            className="earth-observatory__geo-label"
            style={{ left: `${item.left}px`, top: `${item.top}px` }}
            data-node-id={item.nodeId}
          >
            {item.text}
          </p>
        ))}

        <p className="earth-observatory__overline" data-node-id="5:218">
          EARTH OBSERVATORY
        </p>
        <h1 className="earth-observatory__headline" data-node-id="5:219">
          A warming planet, in focus.
        </h1>

        <div className="earth-observatory__period-pill" data-node-id="5:220">
          <p className="earth-observatory__period-text" data-node-id="5:221">
            Jan 2001 — Dec 2025
          </p>
        </div>

        {HOTSPOT_MARKERS.map((hotspot) => {
          const isCoral = hotspot.tone === 'coral'
          return (
            <button
              key={hotspot.id}
              type="button"
              className="earth-observatory__hotspot-btn"
              style={{ left: `${hotspot.left}px`, top: `${hotspot.top}px` }}
              aria-label={`Inspect temperature trend hotspot (${hotspot.trendLabel})`}
              onClick={() => {
                setSelectedHotspotId(hotspot.id)
                setSelectedRegion(hotspot.regionName)
              }}
            >
              <img
                src={isCoral ? figmaAssets.hotspotCoral : figmaAssets.hotspotTeal}
                alt=""
                className="earth-observatory__hotspot-halo"
              />
              <img
                src={
                  isCoral
                    ? figmaAssets.hotspotCoralCenter
                    : figmaAssets.hotspotTealCenter
                }
                alt=""
                className="earth-observatory__hotspot-center"
              />
            </button>
          )
        })}

        <div className="earth-observatory__amazon-aoi" data-node-id="5:234">
          <img src={figmaAssets.amazonBasinSelection} alt="" />
        </div>

        <div className="earth-observatory__callout" data-node-id="5:236">
          <p className="earth-observatory__callout-title" data-node-id="5:237">
            {calloutTitle}
          </p>
          <p className="earth-observatory__callout-value" data-node-id="5:238">
            {activeHotspot.trendLabel}
          </p>
          <p className="earth-observatory__callout-sig" data-node-id="5:239">
            {activeHotspot.significanceLabel}
          </p>
        </div>

        <div className="earth-observatory__leader" data-node-id="5:240">
          <img src={figmaAssets.selectedRegionLeader} alt="" />
        </div>

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
              transform: `translateY(${
                activeMapTool === 'layers'
                  ? 0
                  : activeMapTool === 'region-selection'
                    ? 42
                    : activeMapTool === 'locate'
                      ? 84
                      : activeMapTool === 'zoom-in'
                        ? 126
                        : activeMapTool === 'zoom-out'
                          ? 168
                          : 210
              }px)`,
            }}
          />
          <button
            type="button"
            className="earth-observatory__tool-btn"
            style={{ top: '14px' }}
            data-node-id="5:244"
            aria-label="Map layers"
            aria-pressed={activeMapTool === 'layers'}
            onClick={() => setActiveMapTool('layers')}
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
            onClick={() => setActiveMapTool('region-selection')}
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
              setMapScale(1)
              setSelectedHotspotId('amazon')
              setSelectedRegion('Global land')
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
              setMapScale((scale) => Math.min(1.25, Number((scale + 0.08).toFixed(2))))
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
              setMapScale((scale) => Math.max(0.88, Number((scale - 0.08).toFixed(2))))
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
              navigate(APP_ROUTES.explore)
            }}
          >
            <img src={figmaAssets.fullscreen} alt="" />
          </button>
        </div>

        <div className="earth-observatory__legend" data-node-id="5:258">
          <p className="earth-observatory__legend-title" data-node-id="5:259">
            Temperature trend
          </p>
          <p className="earth-observatory__legend-unit" data-node-id="5:260">
            °C / decade
          </p>
          <div
            className="earth-observatory__legend-bar"
            data-node-id="5:261"
            aria-hidden="true"
          />
          <p className="earth-observatory__legend-min" data-node-id="5:262">
            −0.4
          </p>
          <p className="earth-observatory__legend-zero" data-node-id="5:263">
            0
          </p>
          <p className="earth-observatory__legend-max" data-node-id="5:264">
            +0.8
          </p>
        </div>

        <p className="earth-observatory__equator" data-node-id="5:265">
          0°
        </p>
        <p className="earth-observatory__attribution-left" data-node-id="5:266">
          Natural Earth · NASA MODIS
        </p>
        <p className="earth-observatory__attribution-right" data-node-id="5:267">
          Illustrative spatial trends
        </p>
      </div>
    </section>
  )
}
