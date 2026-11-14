import createClient from 'openapi-fetch'
import type { paths } from './contracts'

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''
export const API_BASE_URL = rawBaseUrl.replace(/\/+$/, '')

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
