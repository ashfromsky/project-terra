import { useQuery } from '@tanstack/react-query'
import { apiFetchClient, ApiError, unwrapApiResponse } from './client'
import type { SystemInfoResponse } from './contracts'

export type { SystemInfoResponse }

export const SYSTEM_INFO_QUERY_KEY = ['system', 'info'] as const

export async function fetchSystemInfo(): Promise<SystemInfoResponse> {
  try {
    const result = await apiFetchClient.GET('/api/v1/system/info')
    return unwrapApiResponse(result, 'GET /api/v1/system/info')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/system/info: ${String(cause)}`)
  }
}

export function useSystemInfoQuery() {
  return useQuery({
    queryKey: SYSTEM_INFO_QUERY_KEY,
    queryFn: fetchSystemInfo,
    staleTime: 60_000,
    retry: 1,
  })
}
