import { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  ExplorerMapViewport,
  type ExplorerMapViewportHandle,
} from '../../features/map-explorer/ui/ExplorerMapViewport'
import { useExploreStore } from '../../features/map-explorer/model/use-explore-store'
import type { MapRenderState } from '../../entities/map/model/map-renderer'
import {
  buildGibsMapLayer,
  findLiveLayer,
  type LiveDomain,
  type LiveEnvironmentLayer,
} from '../../shared/config/live-environment'
import { APP_ROUTES } from '../../shared/config/routes'
import { formatCoordinatePair } from '../../shared/lib/geojson-utils'
import type { MapViewportState } from '../../shared/types/geospatial'
import {
  AlertTriangle,
  Calendar,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
} from '../../shared/ui/explorer-icons'

interface FilterOption {
  key: string
  label: string
  shortLabel: string
  layerId: string
  domain: LiveDomain
}

const SUPPORTED_FILTERS: readonly FilterOption[] = [
  {
    key: 'ndvi',
    label: 'Vegetation Index (NDVI)',
    shortLabel: 'NDVI',
    layerId: 'MODIS_Terra_L3_NDVI_16Day',
    domain: 'vegetation',
  },
  {
    key: 'evi',
    label: 'Enhanced Vegetation (EVI)',
    shortLabel: 'EVI',
    layerId: 'MODIS_Terra_L3_EVI_16Day',
    domain: 'vegetation',
  },
  {
    key: 'lst',
    label: 'Land Surface Temp',
    shortLabel: 'Land temp',
    layerId: 'MODIS_Terra_Land_Surface_Temp_Day',
    domain: 'temperature',
  },
  {
    key: 'precip',
    label: 'Precipitation',
    shortLabel: 'Precipitation',
    layerId: 'IMERG_Precipitation_Rate',
    domain: 'water',
  },
  {
    key: 'soil',
    label: 'Soil Moisture',
    shortLabel: 'Soil moisture',
    layerId: 'SMAP_L4_Analyzed_Surface_Soil_Moisture',
    domain: 'soil',
  },
  {
    key: 'snow',
    label: 'Snow Cover',
    shortLabel: 'Snow cover',
    layerId: 'MODIS_Terra_NDSI_Snow_Cover',
    domain: 'cryosphere',
  },
]

const INITIAL_PREVIEW_VIEWPORT: MapViewportState = {
  center: [15, 20],
  zoom: 1.5,
  bearing: 0,
  pitch: 0,
}

export function LiveEnvironmentalPreview() {
  const navigate = useNavigate()
  const viewportHandleRef = useRef<ExplorerMapViewportHandle | null>(null)

  const verifiedFilters = useMemo(
    () => SUPPORTED_FILTERS.filter((item) => Boolean(findLiveLayer(item.layerId))),
    [],
  )

  const [activeFilterKey, setActiveFilterKey] = useState<string>('ndvi')
  const activeFilter =
    verifiedFilters.find((f) => f.key === activeFilterKey) ?? verifiedFilters[0]

  const activeLayerConfig: LiveEnvironmentLayer | null = useMemo(
    () => findLiveLayer(activeFilter?.layerId ?? null),
    [activeFilter?.layerId],
  )

  const [dateByLayer, setDateByLayer] = useState<Record<string, string>>(() => ({
    MODIS_Terra_L3_NDVI_16Day: '2026-10-16',
    MODIS_Terra_L3_EVI_16Day: '2026-10-16',
    MODIS_Terra_Land_Surface_Temp_Day: '2026-11-14',
    IMERG_Precipitation_Rate: '2026-11-14',
    SMAP_L4_Analyzed_Surface_Soil_Moisture: '2026-11-10',
    MODIS_Terra_NDSI_Snow_Cover: '2026-11-14',
  }))

  const currentDate =
    (activeLayerConfig && dateByLayer[activeLayerConfig.id]) ||
    activeLayerConfig?.defaultObservationDate ||
    '2026-10-16'

  const [hoverCoord, setHoverCoord] = useState<{ lon: number; lat: number } | null>(null)
  const [viewport, setViewport] = useState<MapViewportState>(INITIAL_PREVIEW_VIEWPORT)
  const [rendererWarning, setRendererWarning] = useState<string | null>(null)
  const [rendererError, setRendererError] = useState<string | null>(null)

  const liveMapLayer = useMemo(() => {
    if (!activeLayerConfig) return null
    return buildGibsMapLayer(activeLayerConfig, currentDate)
  }, [activeLayerConfig, currentDate])

  const renderState: MapRenderState = useMemo(
    () => ({
      projection: 'mercator',
      basemap: 'scientific-light',
      selectedDate: currentDate,
      activeLayer: liveMapLayer
        ? {
            layer: liveMapLayer,
            visible: true,
            opacity: 0.86,
            minValue: liveMapLayer.valueRange.defaultMin,
            maxValue: liveMapLayer.valueRange.defaultMax,
          }
        : null,
      showGraticules: false,
      showBorders: true,
      showLabels: true,
      showRegionBoundaries: false,
      interactionMode: 'inspect',
      selectedCountry: null,
      hoveredCountryIso: null,
      inspectedPoint: null,
      aois: [],
      selectedAoiId: null,
      draftVertices: [],
      draftHoverPoint: null,
      viewport,
    }),
    [currentDate, liveMapLayer, viewport],
  )

  const handleSelectFilter = (filterKey: string) => {
    setActiveFilterKey(filterKey)
    const nextFilter = verifiedFilters.find((f) => f.key === filterKey)
    if (nextFilter) {
      const cfg = findLiveLayer(nextFilter.layerId)
      if (cfg && !dateByLayer[cfg.id]) {
        setDateByLayer((prev) => ({ ...prev, [cfg.id]: cfg.defaultObservationDate }))
      }
    }
  }

  const handleDateChange = (newDate: string) => {
    if (!activeLayerConfig || !newDate) return
    setDateByLayer((prev) => ({
      ...prev,
      [activeLayerConfig.id]: newDate,
    }))
  }

  const handleResetDate = () => {
    if (!activeLayerConfig) return
    setDateByLayer((prev) => ({
      ...prev,
      [activeLayerConfig.id]: activeLayerConfig.defaultObservationDate,
    }))
  }

  const handleOpenFullMap = useCallback(() => {
    if (!activeLayerConfig) {
      navigate(APP_ROUTES.explore)
      return
    }
    useExploreStore.getState().setGibsLayer(activeLayerConfig.id)
    useExploreStore.getState().setGibsDate(currentDate)
    navigate(`${APP_ROUTES.explore}?gibs=${activeLayerConfig.id}&date=${currentDate}`)
  }, [activeLayerConfig, currentDate, navigate])

  const legendGradient = useMemo(() => {
    if (!activeLayerConfig || activeLayerConfig.legendStops.length === 0) return ''
    const stops = activeLayerConfig.legendStops
    if (stops.length === 1) return stops[0].color
    return `linear-gradient(to right, ${stops
      .map((stop, i, arr) => `${stop.color} ${(i / (arr.length - 1)) * 100}%`)
      .join(', ')})`
  }, [activeLayerConfig])

  return (
    <div className="observation-panel" aria-label="Live NASA observation preview">
      <div className="observation-panel__head">
        <div className="observation-panel__identity">
          <span
            className={`observation-panel__status${
              rendererError ? ' observation-panel__status--error' : ''
            }`}
          >
            <span className="observation-panel__status-dot" aria-hidden="true" />
            {rendererError ? 'Preview unavailable' : 'Live observation'}
          </span>
          <span className="observation-panel__separator" aria-hidden="true" />
          <span className="observation-panel__layer">
            {activeLayerConfig?.name ?? 'Satellite layer'}
          </span>
        </div>
        <span className="observation-panel__source">
          {activeLayerConfig?.provider ?? 'NASA GIBS'}
        </span>
      </div>

      <div
        className="observation-panel__tabs"
        role="tablist"
        aria-label="Environmental indicator layers"
      >
        {verifiedFilters.map((filter) => {
          const isActive = filter.key === activeFilterKey
          return (
            <button
              key={filter.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-label={filter.label}
              className={`observation-panel__tab${
                isActive ? ' observation-panel__tab--active' : ''
              }`}
              onClick={() => handleSelectFilter(filter.key)}
            >
              {filter.shortLabel}
            </button>
          )
        })}
      </div>

      <div className="observation-panel__stage">
        <ExplorerMapViewport
          ref={viewportHandleRef}
          renderState={renderState}
          onHoverCoordinate={(coords) => setHoverCoord(coords)}
          onViewportChange={(v) => setViewport(v)}
          onRendererStatus={(status) => {
            setRendererWarning(status.warning)
            setRendererError(status.error)
          }}
          ariaLabel="Live interactive satellite preview map"
        />

        <div className="observation-panel__controls" aria-label="Map viewport controls">
          <button
            type="button"
            className="observation-panel__tool"
            title="Zoom in"
            aria-label="Zoom in"
            onClick={() => viewportHandleRef.current?.zoomIn()}
          >
            <Plus size={16} />
          </button>
          <button
            type="button"
            className="observation-panel__tool"
            title="Zoom out"
            aria-label="Zoom out"
            onClick={() => viewportHandleRef.current?.zoomOut()}
          >
            <Minus size={16} />
          </button>
          <button
            type="button"
            className="observation-panel__tool"
            title="Reset world view"
            aria-label="Reset world view"
            onClick={() => viewportHandleRef.current?.resetView()}
          >
            <RotateCcw size={16} />
          </button>
        </div>

        <span className="observation-panel__coords" aria-live="polite">
          {hoverCoord
            ? formatCoordinatePair(hoverCoord.lon, hoverCoord.lat)
            : 'Move over the map to read coordinates'}
        </span>

        {rendererWarning && (
          <div className="observation-panel__warning" role="alert">
            <AlertTriangle size={14} aria-hidden="true" />
            <span>{rendererWarning}</span>
          </div>
        )}
      </div>

      <div className="observation-panel__foot">
        <div className="observation-panel__legend">
          <div className="observation-panel__legend-head">
            <span>{activeLayerConfig?.unit ?? 'Value'} scale</span>
            <span>
              {activeLayerConfig?.valueRange.min} to {activeLayerConfig?.valueRange.max}
            </span>
          </div>
          <div
            className="observation-panel__legend-bar"
            style={{ background: legendGradient }}
            aria-hidden="true"
          />
          <div className="observation-panel__legend-labels" aria-hidden="true">
            {activeLayerConfig?.legendStops.map((stop) => (
              <span key={`${stop.value}-${stop.label}`}>{stop.label}</span>
            ))}
          </div>
        </div>

        <div className="observation-panel__date">
          <label htmlFor="preview-date-input" className="observation-panel__date-label">
            <Calendar size={13} aria-hidden="true" />
            Observation date
          </label>
          <div className="observation-panel__date-controls">
            <input
              id="preview-date-input"
              type="date"
              className="observation-panel__date-input"
              value={currentDate}
              onChange={(e) => handleDateChange(e.target.value)}
            />
            <button
              type="button"
              className="observation-panel__date-reset"
              onClick={handleResetDate}
              title="Reset to the layer's default observation date"
            >
              Reset
            </button>
          </div>
        </div>

        <button
          type="button"
          className="observation-panel__open"
          onClick={handleOpenFullMap}
          aria-label={`Open the full map with ${activeLayerConfig?.shortName ?? 'the selected layer'}`}
        >
          <Maximize2 size={16} aria-hidden="true" />
          Open full map
        </button>
      </div>

      <p className="observation-panel__provenance">
        NASA GIBS tiles are rendered imagery, not numerical input. Quantitative values
        come from{' '}
        <button
          type="button"
          className="observation-panel__inline-link"
          onClick={() => navigate(APP_ROUTES.assessments)}
        >
          assessments
        </button>{' '}
        and browser-side COG reads.
      </p>
    </div>
  )
}
