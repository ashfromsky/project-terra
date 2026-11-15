import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useLayerCatalogQuery } from '../../shared/api/layers'
import { figmaAssets } from '../../shared/config/assets'
import { APP_ROUTES } from '../../shared/config/routes'
import { ObservatoryFrameIcon } from '../../shared/ui/explorer-icons'
import {
  useUiStore,
  type RegionOption,
  type VariableOption,
} from '../../shared/store/ui-store'
import { VARIABLE_TO_LAYER_ID, WorldMap } from '../world-map'

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

export function EarthObservatorySection() {
  const navigate = useNavigate()
  const panelOpen = useUiStore((state) => state.panelOpen)
  const togglePanel = useUiStore((state) => state.togglePanel)
  const selectedVariable = useUiStore((state) => state.selectedVariable)
  const setSelectedVariable = useUiStore((state) => state.setSelectedVariable)
  const selectedRegion = useUiStore((state) => state.selectedRegion)
  const setSelectedRegion = useUiStore((state) => state.setSelectedRegion)
  const setActiveMapTool = useUiStore((state) => state.setActiveMapTool)
  const setSelectedCountry = useUiStore((state) => state.setSelectedCountry)
  const layersQuery = useLayerCatalogQuery()

  const activeLayer = useMemo(() => {
    const targetId = VARIABLE_TO_LAYER_ID[selectedVariable]
    return (layersQuery.data ?? []).find((item) => item.id === targetId) ?? null
  }, [layersQuery.data, selectedVariable])

  const [variableMenuOpen, setVariableMenuOpen] = useState(false)
  const [regionMenuOpen, setRegionMenuOpen] = useState(false)

  return (
    <section
      className="earth-observatory"
      data-node-id="5:112"
      aria-label="Earth observatory"
    >
      <div className="earth-observatory__canvas">
        <WorldMap expandedCanvas={!panelOpen} />

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
            <div
              className="dataset-explorer__divider dataset-explorer__divider--top"
              data-node-id="5:150"
            />

            <p className="dataset-explorer__section-title" data-node-id="5:151">
              NASA datasets
            </p>

            <button
              type="button"
              className="dataset-explorer__dataset-card"
              data-node-id="5:152"
              onClick={() => navigate(APP_ROUTES.dataSources)}
            >
              <span
                className="dataset-explorer__dataset-icon"
                data-node-id="5:153"
              >
                <img src={figmaAssets.dataset} alt="" />
              </span>
              <span
                className="dataset-explorer__dataset-title"
                data-node-id="5:156"
              >
                {activeLayer ? `${activeLayer.productId}.${activeLayer.productVersion}` : 'NASA Earth Observations'}
              </span>
              <span
                className="dataset-explorer__dataset-meta"
                data-node-id="5:157"
              >
                {activeLayer?.availabilityStatus === 'connected'
                  ? `${activeLayer.nativeSpatialResolution} · Connected raster`
                  : `${activeLayer?.nativeSpatialResolution ?? 'Satellite product'} · Unavailable`}
              </span>
              <span
                className="dataset-explorer__dataset-check"
                data-node-id="5:158"
              >
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

            <div
              className="dataset-explorer__divider dataset-explorer__divider--mid"
              data-node-id="5:161"
            />

            <p
              className="dataset-explorer__label dataset-explorer__label--variable"
              data-node-id="5:162"
            >
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
                <span
                  className="dataset-explorer__selector-icon--temp"
                  data-node-id="5:164"
                >
                  <img src={figmaAssets.temperature} alt="" />
                </span>
                <span
                  className="dataset-explorer__selector-text--temp"
                  data-node-id="5:166"
                >
                  {selectedVariable}
                </span>
                <span
                  className="dataset-explorer__selector-chevron"
                  data-node-id="5:167"
                >
                  <img src={figmaAssets.chooseChevron} alt="" />
                </span>
              </button>
              {variableMenuOpen && (
                <ul
                  className="dataset-explorer__menu"
                  role="listbox"
                  aria-label="Select variable"
                >
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

            <p
              className="dataset-explorer__label dataset-explorer__label--region"
              data-node-id="5:169"
            >
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
                <span
                  className="dataset-explorer__selector-icon--region"
                  data-node-id="5:171"
                >
                  <img src={figmaAssets.regionBoundaries} alt="" />
                </span>
                <span
                  className="dataset-explorer__selector-text--region"
                  data-node-id="5:173"
                >
                  {selectedRegion}
                </span>
                <span
                  className="dataset-explorer__selector-chevron"
                  data-node-id="5:174"
                >
                  <img src={figmaAssets.chooseChevron} alt="" />
                </span>
              </button>
              {regionMenuOpen && (
                <ul
                  className="dataset-explorer__menu"
                  role="listbox"
                  aria-label="Select geographic region"
                >
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
                          setSelectedCountry(null)
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

            <div
              className="dataset-explorer__divider dataset-explorer__divider--bottom"
              data-node-id="5:179"
            />

            <p
              className="dataset-explorer__label dataset-explorer__label--method"
              data-node-id="5:180"
            >
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

        <p className="earth-observatory__overline" data-node-id="5:218">
          EARTH OBSERVATORY
        </p>
        <h1 className="earth-observatory__headline" data-node-id="5:219">
          {activeLayer?.name ?? 'Earth observations, in focus.'}
        </h1>

        <div className="earth-observatory__period-pill" data-node-id="5:220">
          <p className="earth-observatory__period-text" data-node-id="5:221">
            {activeLayer?.availabilityStatus === 'connected' &&
            activeLayer.availableDates &&
            activeLayer.availableDates.length > 0
              ? `${activeLayer.availableDates[0]} — ${activeLayer.availableDates[activeLayer.availableDates.length - 1]}`
              : 'No ingested observations'}
          </p>
        </div>

        <Link
          to={APP_ROUTES.explore}
          className="earth-observatory__explore-cta"
          aria-label="Open full-screen Map Explorer at /explore"
        >
          <span className="earth-observatory__explore-cta-icon" aria-hidden="true">
            <ObservatoryFrameIcon size={13} />
          </span>
          <span className="earth-observatory__explore-cta-label">Open Map Explorer</span>
        </Link>
      </div>
    </section>
  )
}
