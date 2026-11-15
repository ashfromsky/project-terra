import type { Layer } from '@deck.gl/core'
import { GeoJsonLayer } from '@deck.gl/layers'
import type { MapLibreOverlay } from '@deck.gl/maplibre'
import type { MapRenderState } from '../model/map-renderer'

export function syncMapLibreDeckOverlay(
  deckOverlay: MapLibreOverlay | null,
  state: MapRenderState,
): void {
  if (state.projection !== 'mercator' || !deckOverlay) return

  const layers: Layer[] = []
  const bbox = state.activeLayer?.visible ? state.activeLayer.layer.datasetBbox : null

  if (bbox && bbox.length === 4) {
    const [minLon, minLat, maxLon, maxLat] = bbox
    layers.push(
      new GeoJsonLayer({
        id: 'explorer-deck-dataset-extent',
        data: {
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              properties: {},
              geometry: {
                type: 'Polygon',
                coordinates: [
                  [
                    [minLon, minLat],
                    [maxLon, minLat],
                    [maxLon, maxLat],
                    [minLon, maxLat],
                    [minLon, minLat],
                  ],
                ],
              },
            },
          ],
        },
        pickable: false,
        stroked: true,
        filled: false,
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: 1.5,
        getLineColor: [21, 155, 145, 220],
      }),
    )
  }

  deckOverlay.setProps({ layers })
}
