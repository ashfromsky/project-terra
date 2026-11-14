import type { Layer, PickingInfo } from '@deck.gl/core'
import { GeoJsonLayer, PolygonLayer, ScatterplotLayer } from '@deck.gl/layers'
import type { Feature } from 'geojson'
import type {
  MapLayerVisibility,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'
import type {
  AnomalyHotspotDatum,
  RegionAoiFeatureProperties,
  SyntheticAnomalyCellDatum,
} from '../model/types'
import {
  ANOMALY_HOTSPOTS,
  REGION_AOI_GEOJSON,
  SYNTHETIC_ANOMALY_CELLS,
} from './cartographic-data'

export interface AnalyticalLayersOptions {
  selectedVariable: VariableOption
  selectedRegion: RegionOption
  selectedHotspotId: string
  visibility: MapLayerVisibility
  onSelectHotspot: (hotspot: AnomalyHotspotDatum) => void
  onSelectRegionAoi: (region: RegionOption) => void
}

function getCellFillColor(
  cell: SyntheticAnomalyCellDatum,
  variable: VariableOption,
  selectedRegion: RegionOption,
): [number, number, number, number] {
  const isFocusedRegion =
    selectedRegion === 'Global land' || cell.regionName === selectedRegion
  const alpha = isFocusedRegion ? 78 : 28

  if (variable === 'Vegetation index (NDVI)') {
    if (cell.ndviScore >= 0.65) return [21, 155, 145, alpha]
    if (cell.ndviScore >= 0.4) return [145, 198, 188, alpha]
    return [223, 184, 146, alpha]
  }

  if (variable === 'Enhanced vegetation (EVI)') {
    if (cell.eviScore >= 0.5) return [14, 124, 116, alpha]
    if (cell.eviScore >= 0.3) return [142, 199, 190, alpha]
    return [229, 203, 176, alpha]
  }

  if (variable === 'Precipitation anomaly') {
    if (cell.precipDelta <= -18) return [199, 127, 109, alpha]
    if (cell.precipDelta < 0) return [222, 180, 159, alpha]
    return [49, 147, 206, alpha]
  }

  if (cell.lstDelta >= 0.38) return [199, 127, 109, alpha]
  if (cell.lstDelta >= 0.3) return [231, 182, 167, alpha]
  return [21, 155, 145, alpha]
}

export function createAnalyticalOverlayLayers({
  selectedVariable,
  selectedRegion,
  selectedHotspotId,
  visibility,
  onSelectHotspot,
  onSelectRegionAoi,
}: AnalyticalLayersOptions): Layer[] {
  const layers: Layer[] = []

  if (visibility.anomalyGrid && visibility.thematicOverlay) {
    layers.push(
      new PolygonLayer<SyntheticAnomalyCellDatum>({
        id: 'terra-synthetic-anomaly-grid',
        data: SYNTHETIC_ANOMALY_CELLS,
        pickable: false,
        stroked: true,
        filled: true,
        wireframe: false,
        lineWidthMinPixels: 0.5,
        getPolygon: (cell) => cell.polygon,
        getFillColor: (cell) =>
          getCellFillColor(cell, selectedVariable, selectedRegion),
        getLineColor: [255, 255, 255, 55],
        updateTriggers: {
          getFillColor: [selectedVariable, selectedRegion],
        },
      }),
    )
  }

  if (visibility.regionBoundaries) {
    layers.push(
      new GeoJsonLayer<RegionAoiFeatureProperties>({
        id: 'terra-region-aoi-boundaries',
        data: REGION_AOI_GEOJSON,
        pickable: true,
        stroked: true,
        filled: true,
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: 1.2,
        lineWidthMaxPixels: 3,
        getFillColor: (feature: Feature) => {
          const props = feature.properties as RegionAoiFeatureProperties | null
          if (!props) return [21, 155, 145, 20]
          const isSelected =
            selectedRegion === props.regionName ||
            (selectedRegion === 'Global land' &&
              props.regionName === 'Amazon basin')
          if (isSelected) {
            return [21, 155, 145, 42]
          }
          return [21, 155, 145, 14]
        },
        getLineColor: (feature: Feature) => {
          const props = feature.properties as RegionAoiFeatureProperties | null
          if (!props) return [21, 155, 145, 180]
          const isSelected =
            selectedRegion === props.regionName ||
            (selectedRegion === 'Global land' &&
              props.regionName === 'Amazon basin')
          return isSelected ? [21, 155, 145, 240] : [21, 155, 145, 115]
        },
        getLineWidth: (feature: Feature) => {
          const props = feature.properties as RegionAoiFeatureProperties | null
          if (!props) return 1.2
          const isSelected =
            selectedRegion === props.regionName ||
            (selectedRegion === 'Global land' &&
              props.regionName === 'Amazon basin')
          return isSelected ? 1.85 : 1.1
        },
        onClick: (info: PickingInfo) => {
          const feature = info.object as Feature | undefined
          const props = feature?.properties as
            | RegionAoiFeatureProperties
            | undefined
          if (props?.regionName) {
            onSelectRegionAoi(props.regionName)
          }
        },
        updateTriggers: {
          getFillColor: [selectedRegion],
          getLineColor: [selectedRegion],
          getLineWidth: [selectedRegion],
        },
      }),
    )
  }

  if (visibility.anomalyHotspots) {
    layers.push(
      new ScatterplotLayer<AnomalyHotspotDatum>({
        id: 'terra-anomaly-hotspots-halo',
        data: ANOMALY_HOTSPOTS,
        pickable: true,
        stroked: true,
        filled: true,
        radiusUnits: 'pixels',
        radiusMinPixels: 10,
        radiusMaxPixels: 18,
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: 1,
        getPosition: (d) => d.coordinates,
        getRadius: (d) => (d.id === selectedHotspotId ? 14 : 10),
        getFillColor: (d) =>
          d.tone === 'teal'
            ? [21, 155, 145, d.id === selectedHotspotId ? 76 : 48]
            : [199, 127, 109, d.id === selectedHotspotId ? 76 : 48],
        getLineColor: (d) =>
          d.tone === 'teal'
            ? [21, 155, 145, d.id === selectedHotspotId ? 210 : 120]
            : [199, 127, 109, d.id === selectedHotspotId ? 210 : 120],
        onClick: (info: PickingInfo<AnomalyHotspotDatum>) => {
          if (info.object) {
            onSelectHotspot(info.object)
          }
        },
        updateTriggers: {
          getRadius: [selectedHotspotId],
          getFillColor: [selectedHotspotId],
          getLineColor: [selectedHotspotId],
        },
      }),
      new ScatterplotLayer<AnomalyHotspotDatum>({
        id: 'terra-anomaly-hotspots-core',
        data: ANOMALY_HOTSPOTS,
        pickable: true,
        stroked: true,
        filled: true,
        radiusUnits: 'pixels',
        radiusMinPixels: 4,
        radiusMaxPixels: 7,
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: 1.5,
        getPosition: (d) => d.coordinates,
        getRadius: (d) => (d.id === selectedHotspotId ? 5.5 : 4.2),
        getFillColor: (d) =>
          d.tone === 'teal' ? [21, 155, 145, 255] : [199, 127, 109, 255],
        getLineColor: [255, 255, 255, 245],
        onClick: (info: PickingInfo<AnomalyHotspotDatum>) => {
          if (info.object) {
            onSelectHotspot(info.object)
          }
        },
        updateTriggers: {
          getRadius: [selectedHotspotId],
        },
      }),
    )
  }

  return layers
}
