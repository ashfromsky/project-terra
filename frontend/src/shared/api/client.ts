import createClient from 'openapi-fetch'
import type { paths } from './contracts'

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''
export const API_BASE_URL = rawBaseUrl.replace(/\/+$/, '')

export const TOKEN_STORAGE_KEY = 'terra_session_token'

export function getStoredToken(): string | null {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') return null
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setStoredToken(token: string | null): void {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') return
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  }
}

// Hydrate token from URL hash (e.g. #session_token=...) on app initialization
if (typeof window !== 'undefined' && window.location.hash.includes('session_token=')) {
  try {
    const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const tokenFromHash = hashParams.get('session_token')
    if (tokenFromHash) {
      setStoredToken(tokenFromHash)
      hashParams.delete('session_token')
      const remainingHash = hashParams.toString()
      const cleanUrl =
        window.location.pathname +
        window.location.search +
        (remainingHash ? `#${remainingHash}` : '')
      window.history.replaceState(null, '', cleanUrl)
    }
  } catch {
    // Ignore URL parse errors
  }
}

/** Error raised for network failures or non-2xx API responses. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string | null

  constructor(status: number, message: string, detail: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export function extractErrorDetail(errorPayload: unknown): string | null {
  if (!errorPayload || typeof errorPayload !== 'object') {
    return null
  }
  const detail = (errorPayload as { detail?: unknown }).detail
  if (typeof detail === 'string' && detail.trim().length > 0) {
    return detail
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const messages = detail
      .map((item) =>
        item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string'
          ? item.msg
          : null,
      )
      .filter((msg): msg is string => Boolean(msg))
    return messages.length > 0 ? messages.join('; ') : null
  }
  return null
}

/** Shared OpenAPI-typed HTTP client bound to `paths` with cookie credentials. */
export const apiFetchClient = createClient<paths>({
  baseUrl: API_BASE_URL,
  credentials: 'include',
})

apiFetchClient.use({
  onRequest({ request }) {
    const token = getStoredToken()
    if (token && !request.headers.get('Authorization')) {
      request.headers.set('Authorization', `Bearer ${token}`)
    }
    return request
  },
})

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}${normalizedPath}`
}

// openapi-fetch wraps response DTOs in `Readable<T>`, which collapses fixed-length tuples
// from generated `schema.d.ts` components (e.g. `rgb: [number, number, number]`) into arrays (`number[]`).
type WidenTuples<T> = T extends readonly (infer E)[]
  ? WidenTuples<E>[]
  : T extends object
    ? { [K in keyof T]: WidenTuples<T[K]> }
    : T

export function unwrapApiResponse<T>(
  result: { data?: NoInfer<WidenTuples<T>>; error?: unknown; response: Response },
  fallbackContext: string,
): T {
  if (!result.response.ok || result.data === undefined) {
    const detail = extractErrorDetail(result.error)
    throw new ApiError(
      result.response.status,
      detail ?? `${fallbackContext} failed with status ${result.response.status}`,
      detail,
    )
  }
  return result.data as T
}
