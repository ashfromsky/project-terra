import type { Layer } from '@deck.gl/core'
import { GeoJsonLayer } from '@deck.gl/layers'
import type { RegionResponse } from '../../../shared/api/contracts'
import type { MapLayerVisibility, RegionOption } from '../../../shared/store/ui-store'
import type { MapLayerDefinition } from '../../../shared/types/geospatial'

export interface AnalyticalOverlayOptions {
  selectedRegion: RegionOption
  regions: readonly RegionResponse[]
  activeLayer: MapLayerDefinition | null
  visibility: MapLayerVisibility
  onSelectRegion?: (region: RegionResponse) => void
}

export function createAnalyticalOverlayLayers({
  regions,
  visibility,
  onSelectRegion,
}: AnalyticalOverlayOptions): Layer[] {
  const layers: Layer[] = []

  if (visibility.regionBoundaries && regions.length > 0) {
    layers.push(
      new GeoJsonLayer<RegionResponse>({
        id: 'terra-user-regions',
        data: {
          type: 'FeatureCollection',
          features: regions.map((region) => ({
            type: 'Feature',
            id: region.id,
            geometry: region.geometry,
            properties: region,
          })),
        },
        pickable: Boolean(onSelectRegion),
        stroked: true,
        filled: true,
        lineWidthMinPixels: 1.5,
        getFillColor: [21, 155, 145, 28],
        getLineColor: [21, 155, 145, 220],
        getLineWidth: 2,
        onClick: onSelectRegion
          ? (info) => {
              const region = info.object?.properties as RegionResponse | undefined
              if (region) {
                onSelectRegion(region)
              }
            }
          : undefined,
      }),
    )
  }

  return layers
}
