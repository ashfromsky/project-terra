import { useEffect, useRef } from 'react'
import type { Map as MapLibreMap, MapGeoJSONFeature, MapLayerMouseEvent } from 'maplibre-gl'
import type {
  CountrySelectionSummary,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'
import type { MapLayerDefinition } from '../../../shared/types/geospatial'
import { REGION_CAMERA_PRESETS } from '../config/cartographic-data'

function parseCountrySummary(
  feature: MapGeoJSONFeature,
): CountrySelectionSummary | null {
  const props = feature.properties
  if (!props || typeof props.isoA3 !== 'string') {
    return null
  }

  return {
    isoA3: props.isoA3,
    name: typeof props.name === 'string' ? props.name : props.isoA3,
    continent: typeof props.continent === 'string' ? props.continent : 'Global',
    subregion: typeof props.subregion === 'string' ? props.subregion : 'Global',
    terraRegion:
      typeof props.terraRegion === 'string'
        ? (props.terraRegion as RegionOption)
        : 'Global land',
    centerLon: Number(props.labelLon ?? 0),
    centerLat: Number(props.labelLat ?? 0),
  }
}

export interface UseRegionInteractionParams {
  mapInstance: MapLibreMap | null
  isMapReady: boolean
  setHoveredCountry: (country: CountrySelectionSummary | null) => void
  selectedCountry: CountrySelectionSummary | null
  setSelectedCountry: (country: CountrySelectionSummary | null) => void
  setSelectedRegion: (region: RegionOption) => void
}

export function useRegionInteraction({
  mapInstance,
  isMapReady,
  setHoveredCountry,
  selectedCountry,
  setSelectedCountry,
  setSelectedRegion,
}: UseRegionInteractionParams) {
  const hoveredFeatureIdRef = useRef<string | number | null>(null)
  const selectedCountryRef = useRef<CountrySelectionSummary | null>(
    selectedCountry,
  )

  useEffect(() => {
    selectedCountryRef.current = selectedCountry
  }, [selectedCountry])

  useEffect(() => {
    if (!mapInstance || !isMapReady) {
      return
    }

    const interactiveLayers = ['country-hit-fill'].filter((layerId) =>
      Boolean(mapInstance.getLayer(layerId)),
    )

    if (interactiveLayers.length === 0) {
      return
    }

    const clearHoverState = () => {
      if (hoveredFeatureIdRef.current !== null) {
        mapInstance.setFeatureState(
          { source: 'ne-countries', id: hoveredFeatureIdRef.current },
          { hover: false },
        )
        hoveredFeatureIdRef.current = null
      }
      mapInstance.getCanvas().style.cursor = ''
      setHoveredCountry(null)
    }

    const handleMouseMove = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0]
      if (!feature) {
        clearHoverState()
        return
      }

      if (
        hoveredFeatureIdRef.current !== null &&
        hoveredFeatureIdRef.current !== feature.id
      ) {
        mapInstance.setFeatureState(
          { source: 'ne-countries', id: hoveredFeatureIdRef.current },
          { hover: false },
        )
      }

      if (feature.id !== undefined) {
        hoveredFeatureIdRef.current = feature.id
        mapInstance.setFeatureState(
          { source: 'ne-countries', id: feature.id },
          { hover: true },
        )
      }

      mapInstance.getCanvas().style.cursor = 'pointer'
      const summary = parseCountrySummary(feature)
      if (summary) {
        setHoveredCountry(summary)
      }
    }

    const handleClick = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0]
      if (!feature) {
        return
      }
      const summary = parseCountrySummary(feature)
      if (!summary) {
        return
      }

      if (selectedCountryRef.current?.isoA3 === summary.isoA3) {
        setSelectedCountry(null)
        return
      }

      setSelectedCountry(summary)
      if (summary.terraRegion !== 'Global land') {
        setSelectedRegion(summary.terraRegion)
      }
    }

    for (const layerId of interactiveLayers) {
      mapInstance.on('mousemove', layerId, handleMouseMove)
      mapInstance.on('mouseleave', layerId, clearHoverState)
      mapInstance.on('click', layerId, handleClick)
    }

    return () => {
      for (const layerId of interactiveLayers) {
        mapInstance.off('mousemove', layerId, handleMouseMove)
        mapInstance.off('mouseleave', layerId, clearHoverState)
        mapInstance.off('click', layerId, handleClick)
      }
    }
  }, [
    isMapReady,
    mapInstance,
    setHoveredCountry,
    setSelectedCountry,
    setSelectedRegion,
  ])
}

export function formatCalloutReadout(
  variable: VariableOption,
  activeLayer: MapLayerDefinition | null,
  selectedRegion: RegionOption,
  activeCountry: CountrySelectionSummary | null,
): {
  title: string
  valueLabel: string
  subtitleLabel: string
  anchorCoordinates: [number, number]
} {
  const isConnected = activeLayer?.availabilityStatus === 'connected'
  const valueLabel = isConnected
    ? `Connected · ${activeLayer.nativeSpatialResolution}`
    : 'Unavailable'
  const temporalLabel =
    activeLayer && activeLayer.availableDates && activeLayer.availableDates.length > 0
      ? `${activeLayer.availableDates[0]} → ${activeLayer.availableDates[activeLayer.availableDates.length - 1]}`
      : activeLayer
        ? `${activeLayer.availableTimeRange.start} → ${activeLayer.availableTimeRange.end}`
        : ''
  const subtitleLabel = isConnected && activeLayer
    ? `${activeLayer.productId}.${activeLayer.productVersion}${temporalLabel ? ` · ${temporalLabel}` : ''}`
    : (activeLayer?.unavailableReason ?? `${variable} dataset not ingested`)

  if (activeCountry) {
    return {
      title: `${activeCountry.name} (${activeCountry.isoA3})`,
      valueLabel,
      subtitleLabel: `${activeCountry.subregion} · ${subtitleLabel}`,
      anchorCoordinates: [activeCountry.centerLon, activeCountry.centerLat],
    }
  }

  const preset = REGION_CAMERA_PRESETS[selectedRegion]
  return {
    title: selectedRegion,
    valueLabel,
    subtitleLabel,
    anchorCoordinates: preset.center,
  }
}
