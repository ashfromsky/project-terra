import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  apiFetchClient,
  ApiError,
  buildApiUrl,
  extractErrorDetail,
  setStoredToken,
  unwrapApiResponse,
} from './client'
import type { AuthCallbackResponse, LogoutResponse, UserResponse } from './contracts'
import { ASSESSMENTS_LIST_QUERY_KEY } from './assessments'
import { REGIONS_QUERY_KEY } from './regions'

export type { AuthCallbackResponse, LogoutResponse, UserResponse }

export const AUTH_ME_QUERY_KEY = ['auth', 'me'] as const

export async function fetchCurrentUser(): Promise<UserResponse | null> {
  try {
    const result = await apiFetchClient.GET('/api/v1/auth/me')
    if (result.response.status === 401) {
      setStoredToken(null)
      return null
    }
    if (!result.response.ok || result.data === undefined) {
      const detail = extractErrorDetail(result.error)
      throw new ApiError(
        result.response.status,
        detail ?? `GET /api/v1/auth/me failed with status ${result.response.status}`,
        detail,
      )
    }
    return result.data
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/auth/me: ${String(cause)}`)
  }
}

export async function logoutSession(): Promise<LogoutResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/auth/logout')
    setStoredToken(null)
    return unwrapApiResponse(result, 'POST /api/v1/auth/logout')
  } catch (cause) {
    setStoredToken(null)
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/auth/logout: ${String(cause)}`)
  }
}

export function buildGitHubLoginUrl(returnTo?: string): string {
  const params = new URLSearchParams({ redirect: 'true' })
  if (returnTo && returnTo.startsWith('/') && !returnTo.startsWith('//')) {
    params.set('returnTo', returnTo)
  }
  return buildApiUrl(`/api/v1/auth/github/login?${params.toString()}`)
}

export function useCurrentUserQuery() {
  return useQuery({
    queryKey: AUTH_ME_QUERY_KEY,
    queryFn: fetchCurrentUser,
    staleTime: 60_000,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 401) return false
      return failureCount < 1
    },
  })
}

export async function loginDevSession(): Promise<AuthCallbackResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/auth/dev-session')
    const session = unwrapApiResponse<AuthCallbackResponse>(result, 'POST /api/v1/auth/dev-session')
    setStoredToken(session.accessToken)
    return session
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling POST /api/v1/auth/dev-session: ${String(cause)}`)
  }
}

export function useDevSessionLoginMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: loginDevSession,
    onSuccess: (session) => {
      queryClient.setQueryData(AUTH_ME_QUERY_KEY, session.user)
      void queryClient.invalidateQueries({ queryKey: REGIONS_QUERY_KEY })
      void queryClient.invalidateQueries({ queryKey: ASSESSMENTS_LIST_QUERY_KEY })
      void queryClient.invalidateQueries({ queryKey: ['data-sources'] })
    },
  })
}

export function useLogoutMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: logoutSession,
    onSuccess: () => {
      queryClient.setQueryData(AUTH_ME_QUERY_KEY, null)
      queryClient.removeQueries({ queryKey: REGIONS_QUERY_KEY })
      queryClient.removeQueries({ queryKey: ASSESSMENTS_LIST_QUERY_KEY })
      queryClient.removeQueries({ queryKey: ['assessments', 'detail'] })
      queryClient.removeQueries({ queryKey: ['data-sources'] })
    },
  })
}
