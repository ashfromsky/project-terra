/**
 * Centralized API client.
 *
 * All backend communication goes through `request()` so error handling,
 * base-URL resolution, and typing stay in one place. `VITE_API_BASE_URL`
 * comes from the root `.env` (see `.env.example`).
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** Error raised for non-2xx API responses. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * Perform a JSON request against the TERRA core API.
 * Paths are absolute (start with `/`) and resolve against `API_BASE_URL`.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { Accept: 'application/json', ...init?.headers },
      ...init,
    })
  } catch (cause) {
    throw new ApiError(0, `Network error calling ${path}: ${String(cause)}`)
  }

  if (!response.ok) {
    throw new ApiError(response.status, `API request to ${path} failed with ${response.status}`)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

/** Shared API surface; endpoint modules build on `request`. */
export const apiClient = {
  baseUrl: API_BASE_URL,
  request,
}
