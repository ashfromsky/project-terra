import type { MapLayerGroupId } from '../../../shared/types/geospatial'

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
