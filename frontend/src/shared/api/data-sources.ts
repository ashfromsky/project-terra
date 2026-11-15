import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchClient, ApiError, unwrapApiResponse } from './client'
import type {
  DiscoverObservationsRequest,
  DiscoverObservationsResponse,
  IngestionOperationResponse,
  PreparedDatasetSummaryResponse,
  ProviderStatusResponse,
  StartIngestionRequest,
} from './contracts'

export const DATA_SOURCES_PROVIDERS_QUERY_KEY = ['data-sources', 'providers'] as const
export const INGESTIONS_LIST_QUERY_KEY = ['data-sources', 'ingestions'] as const

export function ingestionDetailQueryKey(operationId: string) {
  return ['data-sources', 'ingestion', operationId] as const
}

export function datasetsListQueryKey(provider?: string) {
  return ['data-sources', 'datasets', provider ?? 'all'] as const
}

export function datasetDetailQueryKey(datasetId: string) {
  return ['data-sources', 'dataset', datasetId] as const
}

export async function fetchProviders(): Promise<ProviderStatusResponse[]> {
  try {
    const result = await apiFetchClient.GET('/api/v1/data-sources/providers')
    return unwrapApiResponse(result, 'GET /api/v1/data-sources/providers')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling GET /api/v1/data-sources/providers: ${String(cause)}`)
  }
}

export async function discoverObservations(
  body: DiscoverObservationsRequest,
): Promise<DiscoverObservationsResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/data-sources/discover', { body })
    return unwrapApiResponse(result, 'POST /api/v1/data-sources/discover')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling POST /api/v1/data-sources/discover: ${String(cause)}`)
  }
}

export async function startIngestion(
  body: StartIngestionRequest,
): Promise<IngestionOperationResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/data-sources/ingestions', { body })
    return unwrapApiResponse(result, 'POST /api/v1/data-sources/ingestions')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling POST /api/v1/data-sources/ingestions: ${String(cause)}`)
  }
}

export async function fetchIngestions(): Promise<IngestionOperationResponse[]> {
  try {
    const result = await apiFetchClient.GET('/api/v1/data-sources/ingestions')
    return unwrapApiResponse(result, 'GET /api/v1/data-sources/ingestions')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling GET /api/v1/data-sources/ingestions: ${String(cause)}`)
  }
}

export async function fetchIngestionDetail(
  operationId: string,
): Promise<IngestionOperationResponse> {
  try {
    const result = await apiFetchClient.GET('/api/v1/data-sources/ingestions/{operation_id}', {
      params: { path: { operation_id: operationId } },
    })
    return unwrapApiResponse(result, `GET /api/v1/data-sources/ingestions/${operationId}`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(
      0,
      `Network error calling GET /api/v1/data-sources/ingestions/${operationId}: ${String(cause)}`,
    )
  }
}

export async function fetchPreparedDatasets(
  provider?: string,
): Promise<PreparedDatasetSummaryResponse[]> {
  try {
    const result = await apiFetchClient.GET('/api/v1/data-sources/datasets', {
      params: { query: provider ? { provider } : undefined },
    })
    return unwrapApiResponse(result, 'GET /api/v1/data-sources/datasets')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling GET /api/v1/data-sources/datasets: ${String(cause)}`)
  }
}

export async function fetchPreparedDatasetDetail(
  datasetId: string,
): Promise<PreparedDatasetSummaryResponse> {
  try {
    const result = await apiFetchClient.GET('/api/v1/data-sources/datasets/{dataset_id}', {
      params: { path: { dataset_id: datasetId } },
    })
    return unwrapApiResponse(result, `GET /api/v1/data-sources/datasets/${datasetId}`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(
      0,
      `Network error calling GET /api/v1/data-sources/datasets/${datasetId}: ${String(cause)}`,
    )
  }
}

export function useProvidersQuery() {
  return useQuery({
    queryKey: DATA_SOURCES_PROVIDERS_QUERY_KEY,
    queryFn: fetchProviders,
    staleTime: 30_000,
  })
}

export function useIngestionsQuery(enabled = true) {
  return useQuery({
    queryKey: INGESTIONS_LIST_QUERY_KEY,
    queryFn: fetchIngestions,
    enabled,
    refetchInterval: (query) => {
      const items = query.state.data
      if (!items) return false
      return items.some((op) => op.status === 'pending' || op.status === 'running') ? 2500 : false
    },
  })
}

export function useIngestionDetailQuery(operationId: string | null, enabled = true) {
  return useQuery({
    queryKey: ingestionDetailQueryKey(operationId ?? 'none'),
    queryFn: () => fetchIngestionDetail(operationId!),
    enabled: enabled && Boolean(operationId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'running' ? 2000 : false
    },
  })
}

export function usePreparedDatasetsQuery(enabled = true, provider?: string) {
  return useQuery({
    queryKey: datasetsListQueryKey(provider),
    queryFn: () => fetchPreparedDatasets(provider),
    enabled,
    staleTime: 10_000,
  })
}

export function usePreparedDatasetDetailQuery(datasetId: string | null, enabled = true) {
  return useQuery({
    queryKey: datasetDetailQueryKey(datasetId ?? 'none'),
    queryFn: () => fetchPreparedDatasetDetail(datasetId!),
    enabled: enabled && Boolean(datasetId),
  })
}

export function useDiscoverObservationsMutation() {
  return useMutation({
    mutationFn: discoverObservations,
  })
}

export function useStartIngestionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: startIngestion,
    onSuccess: (created) => {
      queryClient.setQueryData(ingestionDetailQueryKey(created.id), created)
      void queryClient.invalidateQueries({ queryKey: INGESTIONS_LIST_QUERY_KEY })
      void queryClient.invalidateQueries({ queryKey: ['data-sources', 'datasets'] })
    },
  })
}
