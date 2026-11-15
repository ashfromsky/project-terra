import { useMemo, useRef } from 'react'
import { useNavigate } from 'react-router'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useCurrentUserQuery } from '../../../shared/api/auth'
import { useLayerCatalogQuery } from '../../../shared/api/layers'
import { useRegionsQuery } from '../../../shared/api/regions'
import { APP_ROUTES } from '../../../shared/config/routes'
import { useUiStore } from '../../../shared/store/ui-store'
import { VARIABLE_TO_LAYER_ID } from '../config/map-style'
import { useWorldMap } from '../lib/use-world-map'
import { MapControlsToolbar } from './MapControlsToolbar'
import { MapLegendCard } from './MapLegendCard'

export interface WorldMapProps {
  expandedCanvas?: boolean
}

export function WorldMap({ expandedCanvas = false }: WorldMapProps) {
  const navigate = useNavigate()
  const mapContainerRef = useRef<HTMLDivElement | null>(null)

  const selectedVariable = useUiStore((state) => state.selectedVariable)
  const selectedRegion = useUiStore((state) => state.selectedRegion)
  const setSelectedRegion = useUiStore((state) => state.setSelectedRegion)
  const selectedCountry = useUiStore((state) => state.selectedCountry)
  const setSelectedCountry = useUiStore((state) => state.setSelectedCountry)
  const hoveredCountry = useUiStore((state) => state.hoveredCountry)
  const setHoveredCountry = useUiStore((state) => state.setHoveredCountry)
  const layerVisibility = useUiStore((state) => state.layerVisibility)

  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)
  const layersQuery = useLayerCatalogQuery()
  const regionsQuery = useRegionsQuery(isAuthenticated)

  const activeLayer = useMemo(() => {
    const targetLayerId = VARIABLE_TO_LAYER_ID[selectedVariable]
    const catalog = layersQuery.data ?? []
    return catalog.find((item) => item.id === targetLayerId) ?? null
  }, [layersQuery.data, selectedVariable])

  const regions = regionsQuery.data ?? []

  const {
    zoomIn,
    zoomOut,
    resetWorldView,
    currentZoom,
    projectedGeoLabels,
    projectedCountryLabels,
  } = useWorldMap({
    containerRef: mapContainerRef,
    selectedVariable,
    selectedRegion,
    setSelectedRegion,
    selectedCountry,
    setSelectedCountry,
    hoveredCountry,
    setHoveredCountry,
    layerVisibility,
    activeLayer,
    regions,
  })

  return (
    <>
      <div
        className={`earth-observatory__world-map ${
          expandedCanvas ? 'earth-observatory__world-map--expanded' : ''
        }`}
        data-node-id="5:185"
      >
        <div
          ref={mapContainerRef}
          className="world-map__viewport"
          aria-label="Interactive world map · OpenFreeMap"
          role="region"
        />

        {layerVisibility.countryLabels && (
          <div className="world-map__labels-layer" aria-hidden="true">
            {projectedGeoLabels.map((label) =>
              label.visible ? (
                <span
                  key={label.id}
                  data-node-id={label.nodeId}
                  className={`world-map__geo-label ${
                    label.kind === 'ocean'
                      ? 'world-map__geo-label--ocean'
                      : 'world-map__geo-label--continent'
                  }`}
                  style={{
                    left: `${label.x}px`,
                    top: `${label.y}px`,
                  }}
                >
                  {label.text}
                </span>
              ) : null,
            )}

            {projectedCountryLabels.map((country) =>
              country.visible ? (
                <span
                  key={country.id}
                  className={`world-map__country-label ${
                    country.isSelected
                      ? 'world-map__country-label--selected'
                      : country.isHovered
                        ? 'world-map__country-label--hovered'
                        : ''
                  }`}
                  style={{
                    left: `${country.x}px`,
                    top: `${country.y}px`,
                  }}
                >
                  {country.text}
                </span>
              ) : null,
            )}
          </div>
        )}
      </div>

      <MapControlsToolbar
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onResetWorldView={resetWorldView}
        onFullscreen={() => navigate(APP_ROUTES.explore)}
        currentZoom={currentZoom}
      />

      <MapLegendCard
        selectedVariable={selectedVariable}
        activeLayer={activeLayer}
      />
    </>
  )
}
