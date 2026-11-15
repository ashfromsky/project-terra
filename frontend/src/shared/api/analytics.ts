import { useQuery } from '@tanstack/react-query'
import { apiFetchClient, ApiError, unwrapApiResponse } from './client'
import type {
  ZonalStatisticsRequest,
  ZonalStatisticsResponse,
  ZonalTimeseriesRequest,
  ZonalTimeseriesResponse,
} from './contracts'

export const ANALYTICS_QUERY_KEYS = {
  zonalStats: (metricId: string, date?: string | null, identifier?: string) =>
    ['analytics', 'zonal-statistics', metricId, date ?? 'latest', identifier ?? 'default'] as const,
  timeseries: (metricId: string, identifier?: string) =>
    ['analytics', 'timeseries', metricId, identifier ?? 'default'] as const,
}

export async function fetchZonalStatistics(
  request: ZonalStatisticsRequest,
): Promise<ZonalStatisticsResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/analytics/zonal-statistics', {
      body: request,
    })
    return unwrapApiResponse(result, 'POST /api/v1/analytics/zonal-statistics')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/analytics/zonal-statistics: ${String(cause)}`)
  }
}

export async function fetchZonalTimeseries(
  request: ZonalTimeseriesRequest,
): Promise<ZonalTimeseriesResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/analytics/zonal-statistics/timeseries', {
      body: request,
    })
    return unwrapApiResponse(result, 'POST /api/v1/analytics/zonal-statistics/timeseries')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(
      0,
      `Network error calling /api/v1/analytics/zonal-statistics/timeseries: ${String(cause)}`,
    )
  }
}

export function useZonalStatisticsQuery(
  params: ZonalStatisticsRequest & { enabled?: boolean; cacheKey?: string },
) {
  const { enabled = true, cacheKey, ...request } = params
  return useQuery({
    queryKey: ANALYTICS_QUERY_KEYS.zonalStats(
      request.metricId,
      request.date,
      cacheKey ?? request.regionId ?? undefined,
    ),
    queryFn: () => fetchZonalStatistics(request),
    enabled: Boolean(enabled && request.metricId && (request.geometry || request.regionId)),
    staleTime: 60_000,
  })
}

export function useZonalTimeseriesQuery(
  params: ZonalTimeseriesRequest & { enabled?: boolean; cacheKey?: string },
) {
  const { enabled = true, cacheKey, ...request } = params
  return useQuery({
    queryKey: ANALYTICS_QUERY_KEYS.timeseries(
      request.metricId,
      cacheKey ?? request.regionId ?? undefined,
    ),
    queryFn: () => fetchZonalTimeseries(request),
    enabled: Boolean(enabled && request.metricId && (request.geometry || request.regionId)),
    staleTime: 60_000,
  })
}
