import type {
  MapLayerDefinition,
  MapLayerGroupId,
} from '../../../shared/types/geospatial'
import { DERIVED_TREND_LAYERS } from './derived-layers'
import { OBSERVATION_LAYERS } from './observation-layers'
import { RESILIENCE_LAYERS } from './resilience-layers'

export interface LayerGroupMeta {
  id: MapLayerGroupId
  label: string
  description: string
}

export const LAYER_GROUPS: readonly LayerGroupMeta[] = [
  {
    id: 'vegetation',
    label: 'Vegetation',
    description: 'MODIS canopy greenness and spectral vegetation indices',
  },
  {
    id: 'temperature',
    label: 'Temperature',
    description: 'Land surface thermal emission and baseline anomalies',
  },
  {
    id: 'water',
    label: 'Water',
    description: 'Precipitation accumulation and surface soil moisture',
  },
  {
    id: 'derived',
    label: 'Derived Indicators',
    description:
      'Trend, significance, ecosystem response, and experimental resilience metrics',
  },
]

export const ENVIRONMENTAL_LAYER_CATALOG: readonly MapLayerDefinition[] = [
  ...OBSERVATION_LAYERS,
  ...DERIVED_TREND_LAYERS,
  ...RESILIENCE_LAYERS,
]

export const LAYER_BY_ID: Record<string, MapLayerDefinition> = Object.fromEntries(
  ENVIRONMENTAL_LAYER_CATALOG.map((layer) => [layer.id, layer]),
)

export function getLayerDefinition(layerId: string): MapLayerDefinition {
  return LAYER_BY_ID[layerId] ?? ENVIRONMENTAL_LAYER_CATALOG[0]
}
