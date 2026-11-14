import { useQuery } from '@tanstack/react-query'
import { defaultMapDataProvider } from '../../../shared/api/map-data-provider'
import type { AoiFeature } from '../../../shared/types/geospatial'

export function useLayerCatalogQuery() {
  return useQuery({
    queryKey: ['map-explorer', 'layers'],
    queryFn: () => defaultMapDataProvider.getLayers(),
    staleTime: Infinity,
  })
}

export function useTemporalCoverageQuery(layerId: string) {
  return useQuery({
    queryKey: ['map-explorer', 'coverage', layerId],
    queryFn: () => defaultMapDataProvider.getTemporalCoverage(layerId),
    enabled: Boolean(layerId),
    staleTime: 60_000,
  })
}

export function usePointInspectionQuery(
  layerId: string,
  point: { lon: number; lat: number } | null,
  date: string,
) {
  return useQuery({
    queryKey: [
      'map-explorer',
      'point-inspect',
      layerId,
      point?.lon ?? null,
      point?.lat ?? null,
      date,
    ],
    queryFn: () =>
      defaultMapDataProvider.inspectPoint({
        layerId,
        longitude: point!.lon,
        latitude: point!.lat,
        date,
      }),
    enabled: Boolean(point && layerId),
    staleTime: 30_000,
  })
}

export function useAreaObservationQuery(
  layerId: string,
  aoi: AoiFeature | null,
  startDate: string,
  endDate: string,
) {
  return useQuery({
    queryKey: [
      'map-explorer',
      'area-observation',
      layerId,
      aoi?.properties.id ?? null,
      startDate,
      endDate,
    ],
    queryFn: () =>
      defaultMapDataProvider.getAreaObservation({
        layerId,
        aoi: aoi!,
        startDate,
        endDate,
      }),
    enabled: Boolean(aoi && layerId),
    staleTime: 30_000,
  })
}
