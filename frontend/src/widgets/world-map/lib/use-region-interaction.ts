import { useCallback, useEffect, useRef } from 'react'
import type { Map as MapLibreMap, MapGeoJSONFeature, MapLayerMouseEvent } from 'maplibre-gl'
import type {
  CountrySelectionSummary,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'
import type { AnomalyHotspotDatum } from '../model/types'
import { ANOMALY_HOTSPOTS } from '../config/cartographic-data'

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
    demoLstTrend: Number(props.demoLstTrend ?? 0.25),
    demoNdvi: Number(props.demoNdvi ?? 0.45),
    demoEvi: Number(props.demoEvi ?? 0.35),
    demoPrecipAnomaly: Number(props.demoPrecipAnomaly ?? 0),
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
  setSelectedHotspotId: (id: string) => void
}

export function useRegionInteraction({
  mapInstance,
  isMapReady,
  setHoveredCountry,
  selectedCountry,
  setSelectedCountry,
  setSelectedRegion,
  setSelectedHotspotId,
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

    const interactiveLayers = ['country-thematic-fill', 'country-base-fill'].filter(
      (layerId) => Boolean(mapInstance.getLayer(layerId)),
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
        const matchingHotspot = ANOMALY_HOTSPOTS.find(
          (item) => item.regionName === summary.terraRegion,
        )
        if (matchingHotspot) {
          setSelectedHotspotId(matchingHotspot.id)
        }
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
    setSelectedHotspotId,
    setSelectedRegion,
  ])

  const selectHotspot = useCallback(
    (hotspot: AnomalyHotspotDatum) => {
      setSelectedHotspotId(hotspot.id)
      setSelectedCountry(null)
      setSelectedRegion(hotspot.regionName)
    },
    [setSelectedCountry, setSelectedHotspotId, setSelectedRegion],
  )

  return {
    selectHotspot,
  }
}

export function formatCalloutReadout(
  variable: VariableOption,
  hotspot: AnomalyHotspotDatum,
  activeCountry: CountrySelectionSummary | null,
): {
  title: string
  valueLabel: string
  subtitleLabel: string
  anchorCoordinates: [number, number]
} {
  if (activeCountry) {
    let valueLabel = `${activeCountry.demoLstTrend >= 0 ? '+' : '−'}${Math.abs(
      activeCountry.demoLstTrend,
    ).toFixed(2)}°C / decade`

    if (variable === 'Vegetation index (NDVI)') {
      valueLabel = `${activeCountry.demoNdvi.toFixed(2)} NDVI mean`
    } else if (variable === 'Enhanced vegetation (EVI)') {
      valueLabel = `${activeCountry.demoEvi.toFixed(2)} EVI mean`
    } else if (variable === 'Precipitation anomaly') {
      const sign = activeCountry.demoPrecipAnomaly >= 0 ? '+' : '−'
      valueLabel = `${sign}${Math.abs(activeCountry.demoPrecipAnomaly).toFixed(1)} mm / mo`
    }

    return {
      title: `${activeCountry.name} (${activeCountry.isoA3})`,
      valueLabel,
      subtitleLabel: `${activeCountry.subregion} · Synthetic demo`,
      anchorCoordinates: [activeCountry.centerLon, activeCountry.centerLat],
    }
  }

  let valueLabel = hotspot.lstTrendLabel
  if (variable === 'Vegetation index (NDVI)') {
    valueLabel = hotspot.ndviLabel
  } else if (variable === 'Enhanced vegetation (EVI)') {
    valueLabel = hotspot.eviLabel
  } else if (variable === 'Precipitation anomaly') {
    valueLabel = hotspot.precipLabel
  }

  return {
    title: hotspot.title,
    valueLabel,
    subtitleLabel: hotspot.significanceLabel,
    anchorCoordinates: hotspot.coordinates,
  }
}
