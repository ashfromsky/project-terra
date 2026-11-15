import {
  MODIS_STAC_SEARCH_ENDPOINT,
  PLANETARY_COMPUTER_SIGN_ENDPOINT,
} from '../../../shared/config/live-environment'

export interface StacAsset {
  href: string
  type?: string
  title?: string
  'raster:bands'?: {
    scale?: number
    offset?: number
    data_type?: string
    unit?: string
    nodata?: number | string
  }[]
}

export interface StacItem {
  id: string
  bbox: [number, number, number, number]
  properties: {
    datetime?: string | null
    start_datetime?: string
    end_datetime?: string
    created?: string
    'proj:transform'?: number[]
    'proj:shape'?: number[]
  }
  assets: Record<string, StacAsset>
}

interface StacSearchResponse {
  type?: string
  features?: StacItem[]
  detail?: string
}

export async function searchStacItems(options: {
  collection: string
  bbox: [number, number, number, number]
  startDate: string
  endDate: string
  limit: number
  signal?: AbortSignal
}): Promise<StacItem[]> {
  const response = await fetch(MODIS_STAC_SEARCH_ENDPOINT, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    signal: options.signal,
    body: JSON.stringify({
      collections: [options.collection],
      bbox: options.bbox,
      datetime: `${options.startDate}T00:00:00Z/${options.endDate}T23:59:59Z`,
      limit: options.limit,
      sortby: [{ field: 'properties.datetime', direction: 'asc' }],
    }),
  })
  if (!response.ok) {
    throw new Error(`Planetary Computer STAC returned HTTP ${response.status}.`)
  }
  const payload = (await response.json()) as StacSearchResponse
  if (!Array.isArray(payload.features)) {
    throw new Error('Planetary Computer STAC returned an unexpected response.')
  }
  return payload.features
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

const signedAssetCache = new Map<string, { href: string; expiresAt: number }>()

export async function signPlanetaryComputerAsset(
  href: string,
  signal?: AbortSignal,
): Promise<string> {
  const cached = signedAssetCache.get(href)
  if (cached && Date.now() < cached.expiresAt - 60_000) {
    return cached.href
  }

  const apiKey =
    typeof import.meta !== 'undefined' && import.meta.env?.VITE_PLANETARY_COMPUTER_API_KEY
  const headers: Record<string, string> = apiKey ? { 'Ocp-Apim-Subscription-Key': apiKey } : {}

  const url = `${PLANETARY_COMPUTER_SIGN_ENDPOINT}?href=${encodeURIComponent(href)}`
  let lastStatus = 0
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const response = await fetch(url, { headers, signal })
    if (response.ok) {
      const payload = (await response.json()) as { href?: string; 'msft:expiry'?: string }
      if (typeof payload.href !== 'string' || payload.href.length === 0) {
        throw new Error('Planetary Computer SAS signing returned no signed asset URL.')
      }
      const expiresAt = payload['msft:expiry']
        ? new Date(payload['msft:expiry']).getTime()
        : Date.now() + 45 * 60 * 1000
      signedAssetCache.set(href, { href: payload.href, expiresAt })
      return payload.href
    }
    lastStatus = response.status
    if (response.status !== 429 && response.status !== 503) break
    const retryAfterHeader = response.headers.get('Retry-After')
    const retryAfterSec = retryAfterHeader ? Number.parseInt(retryAfterHeader, 10) : null
    const waitMs =
      Number.isFinite(retryAfterSec) && (retryAfterSec ?? 0) > 0
        ? (retryAfterSec ?? 1) * 1000
        : 1_500 * 2 ** attempt
    await delay(waitMs)
  }
  if (lastStatus === 429) {
    throw new Error(
      'Microsoft Planetary Computer rate limit exceeded for your IP address (HTTP 429). The public signing endpoint is temporarily throttled by Microsoft. Please wait a minute before retrying, or switch to the "AOI" tab for server-side physical zonal statistics.',
    )
  }
  throw new Error(`Planetary Computer SAS signing returned HTTP ${lastStatus}.`)
}
