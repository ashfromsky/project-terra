import { useCallback, useEffect, useRef, useState } from 'react'
import { MapLibreOverlay } from '@deck.gl/maplibre'
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'
import type {
  CountrySelectionSummary,
  MapLayerVisibility,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'
import {
  ANOMALY_HOTSPOTS,
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
  getThematicFillExpression,
} from '../config/map-style'
import type {
  AnomalyHotspotDatum,
  ProjectedLabelPosition,
  WorldMapController,
} from '../model/types'
import { useRegionInteraction } from './use-region-interaction'

export interface UseWorldMapParams {
  containerRef: React.RefObject<HTMLDivElement | null>
  selectedVariable: VariableOption
  selectedRegion: RegionOption
  setSelectedRegion: (region: RegionOption) => void
  selectedHotspotId: string
  setSelectedHotspotId: (id: string) => void
  selectedCountry: CountrySelectionSummary | null
  setSelectedCountry: (country: CountrySelectionSummary | null) => void
  hoveredCountry: CountrySelectionSummary | null
  setHoveredCountry: (country: CountrySelectionSummary | null) => void
  layerVisibility: MapLayerVisibility
}

export function useWorldMap({
  containerRef,
  selectedVariable,
  selectedRegion,
  setSelectedRegion,
  selectedHotspotId,
  setSelectedHotspotId,
  selectedCountry,
  setSelectedCountry,
  hoveredCountry,
  setHoveredCountry,
  layerVisibility,
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
    selectedVariable,
    selectedRegion,
    selectedCountryIso: selectedCountry?.isoA3 ?? null,
    layerVisibility,
  })

  const latestSelectionRef = useRef({
    selectedCountry,
    hoveredCountry,
    selectedHotspotId,
  })

  useEffect(() => {
    latestSelectionRef.current = {
      selectedCountry,
      hoveredCountry,
      selectedHotspotId,
    }
  }, [hoveredCountry, selectedCountry, selectedHotspotId])

  const updateProjectedPositions = useCallback(() => {
    const map = mapRef.current
    const container = containerRef.current
    if (!map || !container) {
      return
    }

    const {
      selectedCountry: currentSelectedCountry,
      hoveredCountry: currentHoveredCountry,
      selectedHotspotId: currentHotspotId,
    } = latestSelectionRef.current

    const activeHotspot =
      ANOMALY_HOTSPOTS.find((item) => item.id === currentHotspotId) ??
      ANOMALY_HOTSPOTS[0]

    const anchorCoords: [number, number] = currentSelectedCountry
      ? [currentSelectedCountry.centerLon, currentSelectedCountry.centerLat]
      : currentHoveredCountry
        ? [currentHoveredCountry.centerLon, currentHoveredCountry.centerLat]
        : activeHotspot.coordinates

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
          visible: inBounds && rankAllowed,
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
        init.selectedVariable,
        init.selectedRegion,
        init.selectedCountryIso,
        init.layerVisibility,
      ),
      center: preset.center,
      zoom: preset.zoom,
      minZoom: 0.5,
      maxZoom: 6.5,
      renderWorldCopies: false,
      attributionControl: false,
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
    selectedHotspotId,
    updateProjectedPositions,
  ])

  const { selectHotspot } = useRegionInteraction({
    mapInstance,
    isMapReady,
    setHoveredCountry,
    selectedCountry,
    setSelectedCountry,
    setSelectedRegion,
    setSelectedHotspotId,
  })

  const handleSelectRegionAoi = useCallback(
    (region: RegionOption) => {
      setSelectedRegion(region)
      const matchingHotspot = ANOMALY_HOTSPOTS.find(
        (item) => item.regionName === region,
      )
      if (matchingHotspot) {
        setSelectedHotspotId(matchingHotspot.id)
      }
    },
    [setSelectedHotspotId, setSelectedRegion],
  )

  const handleSelectHotspot = useCallback(
    (hotspot: AnomalyHotspotDatum) => {
      selectHotspot(hotspot)
    },
    [selectHotspot],
  )

  useEffect(() => {
    const overlay = deckOverlayRef.current
    if (!overlay || !isMapReady) {
      return
    }

    const layers = createAnalyticalOverlayLayers({
      selectedVariable,
      selectedRegion,
      selectedHotspotId,
      visibility: layerVisibility,
      onSelectHotspot: handleSelectHotspot,
      onSelectRegionAoi: handleSelectRegionAoi,
    })

    overlay.setProps({ layers })
  }, [
    handleSelectHotspot,
    handleSelectRegionAoi,
    isMapReady,
    layerVisibility,
    selectedHotspotId,
    selectedRegion,
    selectedVariable,
  ])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !isMapReady) {
      return
    }

    if (map.getLayer('country-thematic-fill')) {
      map.setPaintProperty(
        'country-thematic-fill',
        'fill-color',
        getThematicFillExpression(selectedVariable),
      )
      map.setLayoutProperty(
        'country-thematic-fill',
        'visibility',
        layerVisibility.thematicOverlay ? 'visible' : 'none',
      )
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
    if (map.getLayer('country-borders')) {
      map.setLayoutProperty('country-borders', 'visibility', borderVis)
    }
    if (map.getLayer('coastline-stroke')) {
      map.setLayoutProperty('coastline-stroke', 'visibility', borderVis)
    }
  }, [
    isMapReady,
    layerVisibility,
    selectedCountry?.isoA3,
    selectedRegion,
    selectedVariable,
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
    setSelectedHotspotId('amazon')
    previousRegionRef.current = 'Global land'
    setSelectedRegion('Global land')
    if (!map) return
    map.easeTo({
      center: INITIAL_WORLD_CAMERA.center,
      zoom: INITIAL_WORLD_CAMERA.zoom,
      duration: 550,
    })
  }, [
    setHoveredCountry,
    setSelectedCountry,
    setSelectedHotspotId,
    setSelectedRegion,
  ])

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
