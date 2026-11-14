import { useQuery } from '@tanstack/react-query'
import { apiFetchClient, ApiError, unwrapApiResponse } from './client'
import type {
  DataAvailabilityStatus,
  MapLayerDefinition,
  MapLayerGroupId,
  TemporalCoverage,
} from '../types/geospatial'

export const LAYERS_CATALOG_QUERY_KEY = ['layers', 'catalog'] as const

export interface FetchLayersParams {
  groupId?: MapLayerGroupId | null
  availabilityStatus?: DataAvailabilityStatus | null
}

export async function fetchLayerCatalog(params?: FetchLayersParams): Promise<MapLayerDefinition[]> {
  try {
    const result = await apiFetchClient.GET('/api/v1/layers', {
      params: {
        query: {
          groupId: params?.groupId ?? undefined,
          availabilityStatus: params?.availabilityStatus ?? undefined,
        },
      },
    })
    return unwrapApiResponse(result, 'GET /api/v1/layers')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/layers: ${String(cause)}`)
  }
}

export async function fetchLayerCoverage(layerId: string): Promise<TemporalCoverage> {
  try {
    const result = await apiFetchClient.GET('/api/v1/layers/{layer_id}/coverage', {
      params: { path: { layer_id: layerId } },
    })
    return unwrapApiResponse(result, `GET /api/v1/layers/${layerId}/coverage`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/layers/${layerId}/coverage: ${String(cause)}`)
  }
}

export function useLayerCatalogQuery() {
  return useQuery({
    queryKey: LAYERS_CATALOG_QUERY_KEY,
    queryFn: () => fetchLayerCatalog(),
    staleTime: 5 * 60_000,
    retry: 1,
  })
}

export function useTemporalCoverageQuery(layerId: string, enabled = true) {
  return useQuery({
    queryKey: ['layers', 'coverage', layerId],
    queryFn: () => fetchLayerCoverage(layerId),
    enabled: Boolean(layerId) && enabled,
    staleTime: 60_000,
    retry: 1,
  })
}
