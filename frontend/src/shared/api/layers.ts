import { useQuery } from '@tanstack/react-query'
import { apiFetchClient, ApiError, buildApiUrl, unwrapApiResponse } from './client'
import type {
  DataAvailabilityStatus,
  LayerPointInspectionResponse,
  MapLayerDefinition,
  MapLayerGroupId,
  TemporalCoverage,
} from '../types/geospatial'

export const LAYERS_CATALOG_QUERY_KEY = ['layers', 'catalog'] as const

export interface FetchLayersParams {
  groupId?: MapLayerGroupId | null
  availabilityStatus?: DataAvailabilityStatus | null
}

export interface InspectLayerPointParams {
  lon: number
  lat: number
  timestamp?: string
  datasetId?: string
}

export function resolveLayerEffectiveDate(
  layer: Pick<MapLayerDefinition, 'availableDates'> | null | undefined,
  selectedDate: string,
): string | undefined {
  const dates = layer?.availableDates
  if (!dates || dates.length === 0) {
    return selectedDate || undefined
  }
  if (dates.includes(selectedDate)) {
    return selectedDate
  }
  return dates[dates.length - 1]
}

export function buildLayerTileUrlTemplate(
  layerId: string,
  params?: { timestamp?: string; vmin?: number; vmax?: number; datasetId?: string },
): string {
  const query = new URLSearchParams()
  if (params?.timestamp) query.set('timestamp', params.timestamp)
  if (params?.vmin !== undefined) query.set('vmin', String(params.vmin))
  if (params?.vmax !== undefined) query.set('vmax', String(params.vmax))
  if (params?.datasetId) query.set('datasetId', params.datasetId)
  const qs = query.toString()
  const path = `/api/v1/layers/${encodeURIComponent(layerId)}/tiles/{z}/{x}/{y}.png`
  return buildApiUrl(qs ? `${path}?${qs}` : path)
}

export function buildLayerRenderPngUrl(
  layerId: string,
  params: {
    bbox: readonly [number, number, number, number] | readonly number[]
    width?: number
    height?: number
    timestamp?: string
    vmin?: number
    vmax?: number
    datasetId?: string
  },
): string {
  const query = new URLSearchParams({
    bbox: params.bbox.slice(0, 4).join(','),
    crs: 'EPSG:4326',
    width: String(params.width ?? 512),
    height: String(params.height ?? 512),
  })
  if (params.timestamp) query.set('timestamp', params.timestamp)
  if (params.vmin !== undefined) query.set('vmin', String(params.vmin))
  if (params.vmax !== undefined) query.set('vmax', String(params.vmax))
  if (params.datasetId) query.set('datasetId', params.datasetId)
  return buildApiUrl(`/api/v1/layers/${encodeURIComponent(layerId)}/render.png?${query.toString()}`)
}

export async function inspectLayerPoint(
  layerId: string,
  params: InspectLayerPointParams,
): Promise<LayerPointInspectionResponse> {
  try {
    const result = await apiFetchClient.GET('/api/v1/layers/{layer_id}/point', {
      params: {
        path: { layer_id: layerId },
        query: {
          lon: params.lon,
          lat: params.lat,
          timestamp: params.timestamp ?? undefined,
          datasetId: params.datasetId ?? undefined,
        },
      },
    })
    return unwrapApiResponse(result, `GET /api/v1/layers/${layerId}/point`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/layers/${layerId}/point: ${String(cause)}`)
  }
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
