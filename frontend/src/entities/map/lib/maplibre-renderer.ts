import { MapLibreOverlay } from '@deck.gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibregl, {
  type Map as MapLibreMap,
  type MapLayerMouseEvent,
  type MapMouseEvent,
} from 'maplibre-gl'
import { BASEMAP_PROVIDER_REGISTRY } from '../../../shared/config/geospatial'
import { clampLatitude, normalizeLongitude } from '../../../shared/lib/geojson-utils'
import type { AoiFeature, BasemapId, MapViewportState, ProjectionId } from '../../../shared/types/geospatial'
import type { CountryFeatureProperties } from '../../../widgets/world-map/model/types'
import {
  countryPropertiesToSummary,
  type MapInteractionHandlers,
  type MapRenderer,
  type MapRendererCapabilities,
  type MapRenderState,
} from '../model/map-renderer'
import { syncMapLibreDeckOverlay } from './maplibre-deck-overlay'
import { renderMapLibreLabels, syncMapLibreLayersAndSources } from './maplibre-overlay-sync'
import { buildMapLibreStyle } from './maplibre-style-builder'

export class MapLibreRenderer implements MapRenderer {
  readonly id = 'maplibre-renderer'
  readonly capabilities: MapRendererCapabilities = {
    supportsDeckGl: true,
    supports3dGlobe: true,
    supportsRasterTiles: true,
    supportsAntimeridianClipping: false,
  }

  private wrapperEl: HTMLDivElement | null = null
  private mapEl: HTMLDivElement | null = null
  private labelsEl: HTMLDivElement | null = null
  private map: MapLibreMap | null = null
  private deckOverlay: MapLibreOverlay | null = null
  private resizeObserver: ResizeObserver | null = null
  private state: MapRenderState | null = null
  private handlers: MapInteractionHandlers
  private isReady = false
  private hoveredFeatureId: string | number | null = null
  private activeProjection: ProjectionId = 'mercator'
  private destroyed = false

  constructor(handlers: MapInteractionHandlers) {
    this.handlers = handlers
  }

  mount(container: HTMLElement): void {
    this.destroyed = false
    const wrapper = document.createElement('div')
    wrapper.className = 'maplibre-stage'
    Object.assign(wrapper.style, { position: 'relative', width: '100%', height: '100%', overflow: 'hidden' })

    const mapDiv = document.createElement('div')
    Object.assign(mapDiv.style, { width: '100%', height: '100%' })

    const labels = document.createElement('div')
    labels.className = 'maplibre-stage__labels'
    Object.assign(labels.style, { position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'hidden', zIndex: '4' })

    wrapper.append(mapDiv, labels)
    container.appendChild(wrapper)

    this.wrapperEl = wrapper
    this.mapEl = mapDiv
    this.labelsEl = labels
  }

  update(state: MapRenderState): void {
    const prevState = this.state
    this.state = state
    if (!this.map && this.mapEl) {
      this.initializeMap(state)
      return
    }
    if (!this.map) return

    if (prevState && prevState.projection !== state.projection) {
      this.applyProjectionMode(state.projection, state.basemap)
    }

    const basemapChanged =
      !prevState ||
      prevState.basemap !== state.basemap ||
      (BASEMAP_PROVIDER_REGISTRY[state.basemap].supportsTemporalTime && prevState.selectedDate !== state.selectedDate)

    if (basemapChanged) {
      this.rebuildStylePreservingState(state)
      return
    }

    if (this.isReady) {
      this.syncVisualState(state)
    }
  }

  setViewport(viewport: MapViewportState, animate = false): void {
    if (!this.map) return
    const opts = { center: viewport.center, zoom: viewport.zoom, bearing: viewport.bearing, pitch: viewport.pitch }
    if (animate) this.map.easeTo({ ...opts, duration: 500 })
    else this.map.jumpTo(opts)
  }

  zoomIn(): void {
    this.map?.zoomIn({ duration: 240 })
  }

  zoomOut(): void {
    this.map?.zoomOut({ duration: 240 })
  }

  resetView(): void {
    this.map?.easeTo({
      center: [10, 18],
      zoom: this.activeProjection === 'globe' ? 1.35 : 1.05,
      bearing: 0,
      pitch: 0,
      duration: 550,
    })
  }

  flyTo(center: [number, number], zoom = 3.2): void {
    this.map?.easeTo({ center, zoom, duration: 600 })
  }

  destroy(): void {
    this.destroyed = true
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    this.detachDeckOverlay()
    if (this.map) {
      this.map.remove()
      this.map = null
    }
    this.wrapperEl?.remove()
    this.wrapperEl = null
    this.mapEl = null
    this.labelsEl = null
    this.isReady = false
  }

  private syncVisualState(state: MapRenderState): void {
    if (!this.map) return
    syncMapLibreLayersAndSources(this.map, state)
    syncMapLibreDeckOverlay(this.deckOverlay, state)
    renderMapLibreLabels(this.map, this.labelsEl, state)
  }

  private initializeMap(state: MapRenderState): void {
    if (!this.mapEl) return
    this.activeProjection = state.projection
    const isGlobe = state.projection === 'globe'

    const map = new maplibregl.Map({
      container: this.mapEl,
      style: buildMapLibreStyle(state),
      center: state.viewport.center,
      zoom: isGlobe ? Math.max(0.8, state.viewport.zoom) : state.viewport.zoom,
      bearing: state.viewport.bearing,
      pitch: state.viewport.pitch,
      minZoom: 0.4,
      maxZoom: 12,
      renderWorldCopies: !isGlobe,
      attributionControl: false,
      dragRotate: isGlobe,
      pitchWithRotate: isGlobe,
    })
    this.map = map

    map.on('style.load', () => {
      if (!this.destroyed && this.state) this.applyProjectionMode(this.state.projection, this.state.basemap)
    })

    map.on('load', () => {
      if (this.destroyed || !this.state) return
      this.isReady = true
      this.applyProjectionMode(this.state.projection, this.state.basemap)
      this.syncVisualState(this.state)
      this.handlers.onRendererStatus?.({
        ready: true,
        error: null,
        deckGlActive: this.state.projection === 'mercator',
        warning: null,
      })
    })

    map.on('error', (event) => {
      if (this.destroyed) return
      const msg = event.error instanceof Error ? event.error.message : 'Tile or rendering warning in MapLibre'
      this.handlers.onRendererStatus?.({
        ready: this.isReady,
        error: null,
        deckGlActive: this.activeProjection === 'mercator' && Boolean(this.deckOverlay),
        warning: msg,
      })
    })

    map.on('move', () => renderMapLibreLabels(this.map, this.labelsEl, this.state))

    map.on('moveend', () => {
      if (!this.map) return
      const c = this.map.getCenter()
      this.handlers.onViewportChange?.({
        center: [normalizeLongitude(c.lng), clampLatitude(c.lat)],
        zoom: Number(this.map.getZoom().toFixed(2)),
        bearing: Number(this.map.getBearing().toFixed(1)),
        pitch: Number(this.map.getPitch().toFixed(1)),
      })
    })

    map.on('mousemove', (event: MapMouseEvent) => this.handleMouseMove(event))
    map.on('mouseout', () => {
      this.clearCountryHover()
      this.handlers.onHoverCoordinate?.(null)
    })
    map.on('click', (event: MapMouseEvent & MapLayerMouseEvent) => this.handleClick(event))
    map.on('dblclick', (event: MapMouseEvent) => {
      if (this.state?.interactionMode !== 'draw-polygon') return
      event.preventDefault()
      this.handlers.onCompleteDraftShape?.(normalizeLongitude(event.lngLat.lng), clampLatitude(event.lngLat.lat))
    })

    if (this.wrapperEl) {
      this.resizeObserver = new ResizeObserver(() => {
        this.map?.resize()
        renderMapLibreLabels(this.map, this.labelsEl, this.state)
      })
      this.resizeObserver.observe(this.wrapperEl)
    }
  }

  private handleMouseMove(event: MapMouseEvent): void {
    const map = this.map
    if (!map || !this.state) return
    const lon = normalizeLongitude(event.lngLat.lng)
    const lat = clampLatitude(event.lngLat.lat)
    this.handlers.onHoverCoordinate?.({ lon, lat })

    if (this.state.interactionMode === 'draw-polygon' || this.state.interactionMode === 'draw-rectangle') {
      this.handlers.onUpdateDraftHover?.([lon, lat])
    }

    if (!map.getLayer('country-thematic-fill')) return
    const feature = map.queryRenderedFeatures(event.point, { layers: ['country-thematic-fill'] })[0]
    if (feature && feature.id !== undefined) {
      if (this.hoveredFeatureId !== null && this.hoveredFeatureId !== feature.id) {
        map.setFeatureState({ source: 'ne-countries', id: this.hoveredFeatureId }, { hover: false })
      }
      this.hoveredFeatureId = feature.id
      map.setFeatureState({ source: 'ne-countries', id: feature.id }, { hover: true })
      map.getCanvas().style.cursor =
        this.state.interactionMode === 'inspect' || this.state.interactionMode === 'select-feature'
          ? 'pointer'
          : 'crosshair'
      this.handlers.onHoverCountry?.(countryPropertiesToSummary(feature.properties as Partial<CountryFeatureProperties>))
    } else {
      this.clearCountryHover()
    }
  }

  private handleClick(event: MapMouseEvent & MapLayerMouseEvent): void {
    const map = this.map
    if (!map || !this.state) return
    const lon = normalizeLongitude(event.lngLat.lng)
    const lat = clampLatitude(event.lngLat.lat)
    const mode = this.state.interactionMode

    if (mode === 'draw-polygon') {
      this.handlers.onAddDraftVertex?.(lon, lat)
      return
    }
    if (mode === 'draw-rectangle') {
      if (this.state.draftVertices.length === 0) this.handlers.onAddDraftVertex?.(lon, lat)
      else this.handlers.onCompleteDraftShape?.(lon, lat)
      return
    }

    if (map.getLayer('country-thematic-fill')) {
      const feature = map.queryRenderedFeatures(event.point, { layers: ['country-thematic-fill'] })[0]
      if (feature) {
        const summary = countryPropertiesToSummary(feature.properties as Partial<CountryFeatureProperties>)
        if (summary) this.handlers.onSelectCountry?.(summary, feature.geometry as AoiFeature['geometry'])
      }
    }
    if (mode === 'inspect') this.handlers.onInspectPoint?.(lon, lat)
  }

  private clearCountryHover(): void {
    if (this.map && this.hoveredFeatureId !== null) {
      try {
        this.map.setFeatureState({ source: 'ne-countries', id: this.hoveredFeatureId }, { hover: false })
      } catch {
        void 0
      }
      this.hoveredFeatureId = null
    }
    if (this.map) {
      this.map.getCanvas().style.cursor =
        this.state?.interactionMode === 'draw-polygon' || this.state?.interactionMode === 'draw-rectangle'
          ? 'crosshair'
          : ''
    }
    this.handlers.onHoverCountry?.(null)
  }

  private applyProjectionMode(projection: ProjectionId, basemap: BasemapId): void {
    const map = this.map
    if (!map) return
    this.activeProjection = projection
    const isGlobe = projection === 'globe'
    map.setProjection({ type: isGlobe ? 'globe' : 'mercator' })

    if (isGlobe) {
      map.dragRotate.enable()
      map.setRenderWorldCopies(false)
      const isLight = basemap === 'scientific-light'
      map.setSky({
        'sky-color': isLight ? '#d8e6eb' : '#08111a',
        'horizon-color': isLight ? '#f4f8fa' : '#142a3a',
        'sky-horizon-blend': 0.75,
        'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 0.7, 8, 0],
      })
      this.detachDeckOverlay()
    } else {
      map.dragRotate.disable()
      map.setBearing(0)
      map.setPitch(0)
      map.setRenderWorldCopies(true)
      map.setSky({ 'atmosphere-blend': 0 })
      this.attachDeckOverlay()
    }

    if (this.state) {
      if (this.state.interactionMode === 'draw-polygon') map.doubleClickZoom.disable()
      else map.doubleClickZoom.enable()
    }

    this.handlers.onRendererStatus?.({
      ready: this.isReady,
      error: null,
      deckGlActive: projection === 'mercator' && Boolean(this.deckOverlay),
      warning: null,
    })
  }

  private attachDeckOverlay(): void {
    if (!this.map || this.deckOverlay) return
    const overlay = new MapLibreOverlay({ interleaved: false, layers: [] })
    this.map.addControl(overlay)
    this.deckOverlay = overlay
  }

  private detachDeckOverlay(): void {
    if (!this.map || !this.deckOverlay) return
    try {
      this.map.removeControl(this.deckOverlay)
    } catch {
      void 0
    }
    this.deckOverlay = null
  }

  private rebuildStylePreservingState(state: MapRenderState): void {
    const map = this.map
    if (!map) return
    this.isReady = false
    const center = map.getCenter()
    const zoom = map.getZoom()
    const bearing = map.getBearing()
    const pitch = map.getPitch()

    map.once('styledata', () => {
      if (this.destroyed || !this.state) return
      this.isReady = true
      map.jumpTo({ center, zoom, bearing, pitch })
      this.applyProjectionMode(this.state.projection, this.state.basemap)
      this.syncVisualState(this.state)
    })

    map.setStyle(buildMapLibreStyle(state))
  }
}
