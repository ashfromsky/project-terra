import type {
  MapViewportState,
  ProjectionId,
} from '../../../shared/types/geospatial'
import type {
  MapInteractionHandlers,
  MapRenderer,
  MapRenderState,
} from '../model/map-renderer'
import { EqualEarthRenderer } from './equal-earth-renderer'
import { MapLibreRenderer } from './maplibre-renderer'

export class MapProjectionController {
  private container: HTMLElement | null = null
  private activeRenderer: MapRenderer | null = null
  private activeEngine: 'd3-geo' | 'maplibre' | null = null
  private handlers: MapInteractionHandlers
  private latestState: MapRenderState | null = null

  constructor(handlers: MapInteractionHandlers) {
    this.handlers = handlers
  }

  mount(container: HTMLElement, initialState: MapRenderState): void {
    this.container = container
    this.latestState = initialState
    this.ensureEngineForProjection(initialState.projection)
    this.activeRenderer?.update(initialState)
  }

  update(state: MapRenderState): void {
    const prevProjection = this.latestState?.projection
    this.latestState = state
    if (prevProjection !== state.projection) {
      this.ensureEngineForProjection(state.projection)
      if (this.activeRenderer && state.viewport) {
        this.activeRenderer.setViewport(state.viewport, false)
      }
    }
    this.activeRenderer?.update(state)
  }

  setViewport(viewport: MapViewportState, animate = false): void {
    this.activeRenderer?.setViewport(viewport, animate)
  }

  zoomIn(): void {
    this.activeRenderer?.zoomIn()
  }

  zoomOut(): void {
    this.activeRenderer?.zoomOut()
  }

  resetView(): void {
    this.activeRenderer?.resetView()
  }

  flyTo(center: [number, number], zoom?: number): void {
    this.activeRenderer?.flyTo(center, zoom)
  }

  getActiveRenderer(): MapRenderer | null {
    return this.activeRenderer
  }

  destroy(): void {
    this.activeRenderer?.destroy()
    this.activeRenderer = null
    this.activeEngine = null
    this.container = null
  }

  private ensureEngineForProjection(projection: ProjectionId): void {
    if (!this.container) return
    const targetEngine: 'd3-geo' | 'maplibre' =
      projection === 'equal-earth' ? 'd3-geo' : 'maplibre'

    if (this.activeEngine === targetEngine && this.activeRenderer) {
      return
    }

    this.activeRenderer?.destroy()
    this.activeRenderer = null
    this.activeEngine = targetEngine

    const renderer =
      targetEngine === 'd3-geo'
        ? new EqualEarthRenderer(this.handlers)
        : new MapLibreRenderer(this.handlers)

    renderer.mount(this.container)
    if (this.latestState) {
      renderer.setViewport(this.latestState.viewport, false)
    }
    this.activeRenderer = renderer
  }
}
