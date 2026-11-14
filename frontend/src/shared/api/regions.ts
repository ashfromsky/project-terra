import { useQuery } from '@tanstack/react-query'
import { apiFetchClient, ApiError, extractErrorDetail, unwrapApiResponse } from './client'
import type {
  RegionCreateRequest,
  RegionGeometryInput,
  RegionResponse,
  RegionStatisticsResponse,
  RegionUpdateGeometryRequest,
  RegionUpdateMetadataRequest,
} from './contracts'
import type { AoiFeature, AoiGeometry } from '../types/geospatial'

export const REGIONS_QUERY_KEY = ['regions', 'list'] as const

export function regionResponseToAoiFeature(region: RegionResponse): AoiFeature {
  return {
    type: 'Feature',
    id: region.id,
    properties: {
      id: region.id,
      name: region.name,
      role: region.role,
      shapeType: region.shapeType,
      sourceCrs: region.sourceCrs,
      approxAreaKm2: region.approxAreaKm2,
      bbox: region.bbox,
      centroid: region.centroid,
      createdAt: region.createdAt,
      isoA3: region.isoA3 ?? undefined,
    },
    geometry: region.geometry,
  }
}

export function toRegionGeometryInput(geometry: AoiGeometry): RegionGeometryInput {
  if (geometry.type === 'Polygon') {
    return {
      type: 'Polygon',
      coordinates: geometry.coordinates.map((ring) =>
        ring.map(([lon, lat]) => [lon, lat] as [number, number]),
      ),
    }
  }
  return {
    type: 'MultiPolygon',
    coordinates: geometry.coordinates.map((polygon) =>
      polygon.map((ring) => ring.map(([lon, lat]) => [lon, lat] as [number, number])),
    ),
  }
}

export async function fetchRegions(): Promise<RegionResponse[]> {
  try {
    const result = await apiFetchClient.GET('/api/v1/regions')
    return unwrapApiResponse(result, 'GET /api/v1/regions')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/regions: ${String(cause)}`)
  }
}

export async function createRegion(body: RegionCreateRequest): Promise<RegionResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/regions', { body })
    return unwrapApiResponse(result, 'POST /api/v1/regions')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling POST /api/v1/regions: ${String(cause)}`)
  }
}

export async function updateRegionMetadata(
  regionId: string,
  body: RegionUpdateMetadataRequest,
): Promise<RegionResponse> {
  try {
    const result = await apiFetchClient.PATCH('/api/v1/regions/{region_id}', {
      params: { path: { region_id: regionId } },
      body,
    })
    return unwrapApiResponse(result, `PATCH /api/v1/regions/${regionId}`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling PATCH /api/v1/regions/${regionId}: ${String(cause)}`)
  }
}

export async function updateRegionGeometry(
  regionId: string,
  body: RegionUpdateGeometryRequest,
): Promise<RegionResponse> {
  try {
    const result = await apiFetchClient.PUT('/api/v1/regions/{region_id}/geometry', {
      params: { path: { region_id: regionId } },
      body,
    })
    return unwrapApiResponse(result, `PUT /api/v1/regions/${regionId}/geometry`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(
      0,
      `Network error calling PUT /api/v1/regions/${regionId}/geometry: ${String(cause)}`,
    )
  }
}

export async function deleteRegion(regionId: string): Promise<void> {
  try {
    const result = await apiFetchClient.DELETE('/api/v1/regions/{region_id}', {
      params: { path: { region_id: regionId } },
    })
    if (!result.response.ok) {
      const detail = extractErrorDetail(result.error)
      throw new ApiError(
        result.response.status,
        detail ?? `DELETE /api/v1/regions/${regionId} failed with status ${result.response.status}`,
        detail,
      )
    }
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling DELETE /api/v1/regions/${regionId}: ${String(cause)}`)
  }
}

export async function fetchRegionStatistics(regionId: string): Promise<RegionStatisticsResponse> {
  try {
    const result = await apiFetchClient.GET('/api/v1/regions/{region_id}/statistics', {
      params: { path: { region_id: regionId } },
    })
    return unwrapApiResponse(result, `GET /api/v1/regions/${regionId}/statistics`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(
      0,
      `Network error calling /api/v1/regions/${regionId}/statistics: ${String(cause)}`,
    )
  }
}

export function useRegionsQuery(enabled: boolean) {
  return useQuery({
    queryKey: REGIONS_QUERY_KEY,
    queryFn: fetchRegions,
    enabled,
    staleTime: 30_000,
    retry: 1,
  })
}

export function useRegionStatisticsQuery(regionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['regions', 'statistics', regionId],
    queryFn: () => fetchRegionStatistics(regionId!),
    enabled: Boolean(regionId) && enabled,
    staleTime: 30_000,
    retry: 1,
  })
}
