import { useEffect, useRef } from 'react'
import {
  Map as MaplibreMap,
  NavigationControl,
} from 'maplibre-gl'
import { MapLibreOverlay } from '@deck.gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'

// MapLibre GL JS v5 embeds its map worker in the main bundle and loads it
// through a Blob URL, so no worker URL setup is required here. (MapLibre v6
// splits the worker into a separate ESM file and would need `setWorkerUrl`;
// sites with a strict CSP can point `maplibregl.workerUrl` at
// `dist/maplibre-gl-csp-worker.js` instead.)

const MAP_STYLE_URL =
  import.meta.env.VITE_MAP_STYLE_URL ?? 'https://tiles.openfreemap.org/styles/positron'

/** Initial map view; individual components own their camera state later. */
const INITIAL_VIEW = {
  center: [0, 20] as [number, number],
  zoom: 1.5,
}

interface MapViewProps {
  className?: string
}

/**
 * Minimal MapLibre map with the deck.gl integration attached.
 *
 * `MapLibreOverlay` (overlaid mode by default) is the deck.gl integration for
 * MapLibre GL JS v5; pass `interleaved: true` to share MapLibre's WebGL2
 * context when layer ordering against base-map layers is needed. Actual
 * deck.gl layers are registered through app state later; `layers` stays empty
 * for now.
 */
export function MapView({ className }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const map = new MaplibreMap({
      container,
      style: MAP_STYLE_URL,
      center: INITIAL_VIEW.center,
      zoom: INITIAL_VIEW.zoom,
    })

    map.addControl(new MapLibreOverlay({ layers: [] }))
    map.addControl(new NavigationControl({ visualizePitch: true }), 'top-right')

    return () => {
      map.remove()
    }
  }, [])

  return <div ref={containerRef} className={className} />
}
