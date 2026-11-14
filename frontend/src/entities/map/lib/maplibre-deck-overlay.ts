import type { Layer } from '@deck.gl/core'
import { GeoJsonLayer, PolygonLayer } from '@deck.gl/layers'
import type { MapLibreOverlay } from '@deck.gl/maplibre'
import type { MapLayerDefinition } from '../../../shared/types/geospatial'
import {
  REGION_AOI_GEOJSON,
  SYNTHETIC_ANOMALY_CELLS,
} from '../../../widgets/world-map/config/cartographic-data'
import type { SyntheticAnomalyCellDatum } from '../../../widgets/world-map/model/types'
import { interpolateColorFromLayer } from '../../layer/lib/layer-coloring'
import type { MapRenderState } from '../model/map-renderer'

function parseHexOrRgbToTuple(color: string, alpha: number): [number, number, number, number] {
  if (color.startsWith('#') && color.length === 7) {
    return [
      parseInt(color.slice(1, 3), 16),
      parseInt(color.slice(3, 5), 16),
      parseInt(color.slice(5, 7), 16),
      alpha,
    ]
  }
  const match = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/)
  if (match) {
    return [Number(match[1]), Number(match[2]), Number(match[3]), alpha]
  }
  return [145, 198, 188, alpha]
}

function getGridCellPreviewValue(
  cell: SyntheticAnomalyCellDatum,
  layer: MapLayerDefinition,
): number | null {
  switch (layer.previewPropertyKey) {
    case 'demoLstTrend':
      return cell.lstDelta
    case 'demoNdvi':
      return cell.ndviScore
    case 'demoEvi':
      return cell.eviScore
    case 'demoPrecipAnomaly':
      return cell.precipDelta
    default:
      return null
  }
}

export function syncMapLibreDeckOverlay(
  deckOverlay: MapLibreOverlay | null,
  state: MapRenderState,
): void {
  if (state.projection !== 'mercator' || !deckOverlay) return

  const layers: Layer[] = []
  if (
    state.activeLayer &&
    state.activeLayer.visible &&
    state.syntheticPreviewEnabled &&
    state.activeLayer.layer.isSyntheticPreview &&
    state.activeLayer.layer.renderingType === 'raster'
  ) {
    const active = state.activeLayer
    const alpha = Math.round(active.opacity * 170)
    layers.push(
      new PolygonLayer<SyntheticAnomalyCellDatum>({
        id: 'explorer-deck-synthetic-grid',
        data: SYNTHETIC_ANOMALY_CELLS,
        pickable: false,
        stroked: true,
        filled: true,
        lineWidthMinPixels: 0.5,
        getPolygon: (cell) => cell.polygon,
        getFillColor: (cell) => {
          const val = getGridCellPreviewValue(cell, active.layer)
          const color = interpolateColorFromLayer(active.layer, val, active.minValue, active.maxValue)
          return parseHexOrRgbToTuple(color, alpha)
        },
        getLineColor: [255, 255, 255, 45],
        updateTriggers: {
          getFillColor: [active.layer.id, active.opacity, active.minValue, active.maxValue],
        },
      }),
    )
  }

  if (state.showRegionBoundaries) {
    layers.push(
      new GeoJsonLayer({
        id: 'explorer-deck-region-aois',
        data: REGION_AOI_GEOJSON,
        pickable: false,
        stroked: true,
        filled: false,
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: 1.2,
        getLineColor: [21, 155, 145, 190],
      }),
    )
  }

  deckOverlay.setProps({ layers })
}
