import { useQuery } from '@tanstack/react-query'
import { apiClient } from './client'

/** Response shape of the backend health endpoints. */
export interface HealthStatus {
  status: string
  service?: string
  version?: string
}

/** Fetch the backend health probe. */
export async function fetchHealth(): Promise<HealthStatus> {
  return apiClient.request<HealthStatus>('/health')
}

/** Server state for the API health probe (TanStack Query). */
export function useHealthQuery() {
  return useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
  })
}
