import { useQuery } from '@tanstack/react-query'
import { apiFetchClient, ApiError, unwrapApiResponse } from './client'
import type { HealthResponse } from './contracts'

export type { HealthResponse }

export async function fetchHealth(): Promise<HealthResponse> {
  try {
    const result = await apiFetchClient.GET('/health')
    return unwrapApiResponse(result, 'GET /health')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /health: ${String(cause)}`)
  }
}

export function useHealthQuery() {
  return useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    retry: 1,
  })
}
