import type { Layer } from '@deck.gl/core'
import { GeoJsonLayer } from '@deck.gl/layers'
import type { Feature, Polygon } from 'geojson'
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

function buildDatasetExtentFeature(
  bbox: readonly number[],
  layer: MapLayerDefinition,
): Feature<Polygon, { title: string; subtitle: string }> {
  const [west, south, east, north] = bbox
  return {
    type: 'Feature',
    properties: {
      title: `${layer.name} coverage`,
      subtitle: `${layer.productId}.${layer.productVersion} · ${layer.nativeSpatialResolution}`,
    },
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [west, south],
          [east, south],
          [east, north],
          [west, north],
          [west, south],
        ],
      ],
    },
  }
}

export function createAnalyticalOverlayLayers({
  regions,
  activeLayer,
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

  if (
    visibility.thematicOverlay &&
    activeLayer &&
    activeLayer.availabilityStatus === 'connected' &&
    activeLayer.datasetBbox &&
    activeLayer.datasetBbox.length === 4
  ) {
    layers.push(
      new GeoJsonLayer({
        id: 'terra-dataset-extent-outline',
        data: {
          type: 'FeatureCollection',
          features: [buildDatasetExtentFeature(activeLayer.datasetBbox, activeLayer)],
        },
        pickable: false,
        stroked: true,
        filled: false,
        lineWidthMinPixels: 1.5,
        getLineColor: [11, 114, 133, 210],
        getLineWidth: 2,
      }),
    )
  }

  return layers
}
