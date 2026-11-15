import { useCallback, useEffect, useRef, useState } from 'react'
import { MapLibreOverlay } from '@deck.gl/maplibre'
import maplibregl, { type Map as MapLibreMap, type RasterTileSource } from 'maplibre-gl'
import type { RegionResponse } from '../../../shared/api/contracts'
import { buildLayerTileUrlTemplate, resolveLayerEffectiveDate } from '../../../shared/api/layers'
import type {
  CountrySelectionSummary,
  MapLayerVisibility,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'
import type { MapLayerDefinition } from '../../../shared/types/geospatial'
import {
  CONTINENT_AND_OCEAN_LABELS,
  INITIAL_WORLD_CAMERA,
  MAJOR_COUNTRY_LABELS,
  REGION_CAMERA_PRESETS,
} from '../config/cartographic-data'
import { createAnalyticalOverlayLayers } from '../config/analytical-layers'
import {
  buildInitialMapStyle,
  buildRegionHighlightExpression,
  buildSelectedCountryFillExpression,
  buildSelectedCountryLineExpression,
} from '../config/map-style'
import type {
  ProjectedLabelPosition,
  WorldMapController,
} from '../model/types'
import { useRegionInteraction } from './use-region-interaction'

export interface UseWorldMapParams {
  containerRef: React.RefObject<HTMLDivElement | null>
  selectedVariable: VariableOption
  selectedRegion: RegionOption
  setSelectedRegion: (region: RegionOption) => void
  selectedCountry: CountrySelectionSummary | null
  setSelectedCountry: (country: CountrySelectionSummary | null) => void
  hoveredCountry: CountrySelectionSummary | null
  setHoveredCountry: (country: CountrySelectionSummary | null) => void
  layerVisibility: MapLayerVisibility
  activeLayer: MapLayerDefinition | null
  regions: readonly RegionResponse[]
  selectedDate?: string
}

export function useWorldMap({
  containerRef,
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
  selectedDate,
}: UseWorldMapParams): WorldMapController {
  const mapRef = useRef<MapLibreMap | null>(null)
  const deckOverlayRef = useRef<MapLibreOverlay | null>(null)
  const [mapInstance, setMapInstance] = useState<MapLibreMap | null>(null)
  const [isMapReady, setIsMapReady] = useState(false)
  const [currentZoom, setCurrentZoom] = useState(INITIAL_WORLD_CAMERA.zoom)
  const [projectedGeoLabels, setProjectedGeoLabels] = useState<
    readonly ProjectedLabelPosition[]
  >([])
  const [projectedCountryLabels, setProjectedCountryLabels] = useState<
    readonly ProjectedLabelPosition[]
  >([])
  const [calloutPixelAnchor, setCalloutPixelAnchor] = useState<{
    x: number
    y: number
  } | null>(null)

  const initialConfigRef = useRef({
    selectedRegion,
    selectedCountryIso: selectedCountry?.isoA3 ?? null,
    layerVisibility,
    activeLayer,
  })

  const latestSelectionRef = useRef({
    selectedCountry,
    hoveredCountry,
    selectedRegion,
  })

  useEffect(() => {
    latestSelectionRef.current = {
      selectedCountry,
      hoveredCountry,
      selectedRegion,
    }
  }, [hoveredCountry, selectedCountry, selectedRegion])

  const updateProjectedPositions = useCallback(() => {
    const map = mapRef.current
    const container = containerRef.current
    if (!map || !container) {
      return
    }

    const {
      selectedCountry: currentSelectedCountry,
      hoveredCountry: currentHoveredCountry,
      selectedRegion: currentRegion,
    } = latestSelectionRef.current

    const regionPreset =
      REGION_CAMERA_PRESETS[currentRegion] ?? INITIAL_WORLD_CAMERA
    const anchorCoords: [number, number] = currentSelectedCountry
      ? [currentSelectedCountry.centerLon, currentSelectedCountry.centerLat]
      : currentHoveredCountry
        ? [currentHoveredCountry.centerLon, currentHoveredCountry.centerLat]
        : regionPreset.center

    const width = container.clientWidth
    const height = container.clientHeight
    const zoom = map.getZoom()
    setCurrentZoom(Number(zoom.toFixed(2)))

    const nextGeoLabels: ProjectedLabelPosition[] =
      CONTINENT_AND_OCEAN_LABELS.map((item) => {
        const pt = map.project([item.longitude, item.latitude])
        const inBounds =
          pt.x >= 24 && pt.x <= width - 24 && pt.y >= 18 && pt.y <= height - 18
        return {
          id: item.id,
          text: item.text,
          x: Math.round(pt.x),
          y: Math.round(pt.y),
          visible: inBounds && zoom <= 3.3,
          kind: item.kind,
          nodeId: item.nodeId,
        }
      })

    const maxRank = zoom >= 2.5 ? 3 : zoom >= 1.55 ? 2 : 1
    const nextCountryLabels: ProjectedLabelPosition[] = MAJOR_COUNTRY_LABELS.map(
      (country) => {
        const pt = map.project([country.longitude, country.latitude])
        const inBounds =
          pt.x >= 32 && pt.x <= width - 32 && pt.y >= 24 && pt.y <= height - 24
        const isSelected = currentSelectedCountry?.isoA3 === country.isoA3
        const isHovered = currentHoveredCountry?.isoA3 === country.isoA3
        const rankAllowed =
          country.labelRank <= maxRank || isSelected || isHovered
        return {
          id: `country-${country.isoA3}`,
          text: country.name,
          x: Math.round(pt.x),
          y: Math.round(pt.y),
          visible: inBounds && zoom <= 3.8 && rankAllowed,
          kind: 'country',
          isoA3: country.isoA3,
          isSelected,
          isHovered,
        }
      },
    )

    const anchorPoint = map.project(anchorCoords)
    setProjectedGeoLabels(nextGeoLabels)
    setProjectedCountryLabels(nextCountryLabels)
    setCalloutPixelAnchor({
      x: Math.round(anchorPoint.x),
      y: Math.round(anchorPoint.y),
    })
  }, [containerRef])

  useEffect(() => {
    const container = containerRef.current
    if (!container || mapRef.current) {
      return
    }

    const init = initialConfigRef.current
    const preset =
      REGION_CAMERA_PRESETS[init.selectedRegion] ?? INITIAL_WORLD_CAMERA

    const map = new maplibregl.Map({
      container,
      style: buildInitialMapStyle(
        init.selectedRegion,
        init.selectedCountryIso,
        init.layerVisibility,
        init.activeLayer,
      ),
      center: preset.center,
      zoom: preset.zoom,
      minZoom: 0.5,
      maxZoom: 18,
      renderWorldCopies: false,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
      touchZoomRotate: true,
    })

    const deckOverlay = new MapLibreOverlay({
      interleaved: false,
      layers: [],
    })

    map.addControl(deckOverlay)
    mapRef.current = map
    deckOverlayRef.current = deckOverlay
    setMapInstance(map)

    const handleLoad = () => {
      setIsMapReady(true)
      updateProjectedPositions()
    }

    map.on('load', handleLoad)
    map.on('move', updateProjectedPositions)
    map.on('zoom', updateProjectedPositions)
    map.on('resize', updateProjectedPositions)

    const resizeObserver = new ResizeObserver(() => {
      map.resize()
      updateProjectedPositions()
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      map.off('load', handleLoad)
      map.off('move', updateProjectedPositions)
      map.off('zoom', updateProjectedPositions)
      map.off('resize', updateProjectedPositions)
      map.remove()
      mapRef.current = null
      deckOverlayRef.current = null
      setMapInstance(null)
      setIsMapReady(false)
    }
  }, [containerRef, updateProjectedPositions])

  useEffect(() => {
    updateProjectedPositions()
  }, [
    hoveredCountry?.isoA3,
    selectedCountry?.isoA3,
    selectedRegion,
    updateProjectedPositions,
  ])

  useRegionInteraction({
    mapInstance,
    isMapReady,
    setHoveredCountry,
    selectedCountry,
    setSelectedCountry,
    setSelectedRegion,
  })

  useEffect(() => {
    const overlay = deckOverlayRef.current
    if (!overlay || !isMapReady) {
      return
    }

    const layers = createAnalyticalOverlayLayers({
      selectedRegion,
      regions,
      activeLayer,
      visibility: layerVisibility,
    })

    overlay.setProps({ layers })
  }, [activeLayer, isMapReady, layerVisibility, regions, selectedRegion])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !isMapReady) {
      return
    }

    const effectiveDate = resolveLayerEffectiveDate(activeLayer, selectedDate ?? '')
    const tileUrl =
      activeLayer && activeLayer.availabilityStatus === 'connected'
        ? buildLayerTileUrlTemplate(activeLayer.id, { timestamp: effectiveDate })
        : null

    if (tileUrl) {
      const existingSource = map.getSource('terra-science-raster') as
        | RasterTileSource
        | undefined
      if (existingSource) {
        existingSource.setTiles([tileUrl])
      } else {
        map.addSource('terra-science-raster', {
          type: 'raster',
          tiles: [tileUrl],
          tileSize: 256,
          maxzoom: 12,
        })
      }
      if (!map.getLayer('active-science-raster')) {
        map.addLayer(
          {
            id: 'active-science-raster',
            type: 'raster',
            source: 'terra-science-raster',
            layout: {
              visibility: layerVisibility.thematicOverlay ? 'visible' : 'none',
            },
            paint: {
              'raster-opacity': 0.82,
              'raster-resampling': 'nearest',
              'raster-fade-duration': 100,
            },
          },
          map.getLayer('graticule-grid-lines') ? 'graticule-grid-lines' : undefined,
        )
      } else {
        map.setLayoutProperty(
          'active-science-raster',
          'visibility',
          layerVisibility.thematicOverlay ? 'visible' : 'none',
        )
      }
    } else {
      if (map.getLayer('active-science-raster')) {
        map.removeLayer('active-science-raster')
      }
      if (map.getSource('terra-science-raster')) {
        map.removeSource('terra-science-raster')
      }
    }

    if (map.getLayer('country-region-highlight-fill')) {
      map.setPaintProperty(
        'country-region-highlight-fill',
        'fill-color',
        buildRegionHighlightExpression(selectedRegion),
      )
      map.setLayoutProperty(
        'country-region-highlight-fill',
        'visibility',
        layerVisibility.regionBoundaries ? 'visible' : 'none',
      )
    }

    const selectedIso = selectedCountry?.isoA3 ?? null
    if (map.getLayer('country-selected-fill')) {
      map.setPaintProperty(
        'country-selected-fill',
        'fill-color',
        buildSelectedCountryFillExpression(selectedIso),
      )
    }
    if (map.getLayer('country-selected-outline')) {
      map.setPaintProperty(
        'country-selected-outline',
        'line-width',
        buildSelectedCountryLineExpression(selectedIso),
      )
    }

    const graticuleVis = layerVisibility.graticules ? 'visible' : 'none'
    if (map.getLayer('graticule-grid-lines')) {
      map.setLayoutProperty('graticule-grid-lines', 'visibility', graticuleVis)
    }
    if (map.getLayer('graticule-equator-line')) {
      map.setLayoutProperty('graticule-equator-line', 'visibility', graticuleVis)
    }

    const borderVis = layerVisibility.countryBorders ? 'visible' : 'none'
    for (const borderLayerId of [
      'country-borders',
      'ofm-boundary-country',
      'ofm-boundary-subnational',
    ]) {
      if (map.getLayer(borderLayerId)) {
        map.setLayoutProperty(borderLayerId, 'visibility', borderVis)
      }
    }
  }, [
    activeLayer,
    isMapReady,
    layerVisibility,
    selectedCountry?.isoA3,
    selectedRegion,
    selectedVariable,
    selectedDate,
  ])

  const previousRegionRef = useRef<RegionOption>(selectedRegion)

  useEffect(() => {
    const map = mapRef.current
    if (!map || !isMapReady) {
      return
    }
    if (previousRegionRef.current === selectedRegion) {
      return
    }
    previousRegionRef.current = selectedRegion

    const preset =
      REGION_CAMERA_PRESETS[selectedRegion] ?? INITIAL_WORLD_CAMERA
    map.easeTo({
      center: preset.center,
      zoom: preset.zoom,
      duration: 650,
    })
  }, [isMapReady, selectedRegion])

  const zoomIn = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    map.zoomIn({ duration: 260 })
  }, [])

  const zoomOut = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    map.zoomOut({ duration: 260 })
  }, [])

  const resetWorldView = useCallback(() => {
    const map = mapRef.current
    setSelectedCountry(null)
    setHoveredCountry(null)
    previousRegionRef.current = 'Global land'
    setSelectedRegion('Global land')
    if (!map) return
    map.easeTo({
      center: INITIAL_WORLD_CAMERA.center,
      zoom: INITIAL_WORLD_CAMERA.zoom,
      duration: 550,
    })
  }, [setHoveredCountry, setSelectedCountry, setSelectedRegion])

  const flyToRegion = useCallback(
    (region: RegionOption) => {
      const map = mapRef.current
      previousRegionRef.current = region
      setSelectedRegion(region)
      if (!map) return
      const preset = REGION_CAMERA_PRESETS[region] ?? INITIAL_WORLD_CAMERA
      map.easeTo({
        center: preset.center,
        zoom: preset.zoom,
        duration: 650,
      })
    },
    [setSelectedRegion],
  )

  const flyToCoordinates = useCallback(
    (longitude: number, latitude: number, zoom = 2.8) => {
      const map = mapRef.current
      if (!map) return
      map.easeTo({
        center: [longitude, latitude],
        zoom,
        duration: 600,
      })
    },
    [],
  )

  return {
    zoomIn,
    zoomOut,
    resetWorldView,
    flyToRegion,
    flyToCoordinates,
    currentZoom,
    isMapReady,
    projectedGeoLabels,
    projectedCountryLabels,
    calloutPixelAnchor,
  }
}
