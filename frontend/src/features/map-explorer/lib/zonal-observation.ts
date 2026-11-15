import { resolveLayerEffectiveDate } from '../../../shared/api/layers'
import type { MapLayerDefinition } from '../../../shared/types/geospatial'

export interface ZonalObservationPlan {
  /** Observation date to request; undefined lets Core fall back to the layer's latest ingested date. */
  date: string | undefined
  /** Date to show while no backend response has confirmed the observation date. */
  displayDate: string
  /** True when the requested date is outside the ingested record for this layer. */
  dateWasAdjusted: boolean
  /** True when the layer points at an ingested raster dataset. */
  hasIngestedDataset: boolean
}

export function resolveZonalObservation(
  layer: Pick<MapLayerDefinition, 'availableDates' | 'activeDatasetId'> | null | undefined,
  requestedDate: string,
): ZonalObservationPlan {
  const availableDates = layer?.availableDates ?? []
  const date =
    availableDates.length > 0 ? resolveLayerEffectiveDate(layer, requestedDate) : undefined
  return {
    date,
    displayDate: date ?? requestedDate,
    dateWasAdjusted: Boolean(date && date !== requestedDate),
    hasIngestedDataset: Boolean(layer?.activeDatasetId),
  }
}
