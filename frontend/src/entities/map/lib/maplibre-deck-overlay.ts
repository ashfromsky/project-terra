import type { Layer } from '@deck.gl/core'
import type { MapLibreOverlay } from '@deck.gl/maplibre'
import type { MapRenderState } from '../model/map-renderer'

export function syncMapLibreDeckOverlay(
  deckOverlay: MapLibreOverlay | null,
  state: MapRenderState,
): void {
  if (state.projection !== 'mercator' || !deckOverlay) return

  const layers: Layer[] = []
  deckOverlay.setProps({ layers })
}

