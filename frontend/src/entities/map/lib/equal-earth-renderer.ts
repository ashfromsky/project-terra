import { geoPath } from 'd3-geo'
import { BASEMAP_PROVIDER_REGISTRY } from '../../../shared/config/geospatial'
import { clampLatitude, normalizeAoiGeometry, normalizeLongitude } from '../../../shared/lib/geojson-utils'
import type { BasemapId, MapViewportState } from '../../../shared/types/geospatial'
import { loadNaturalEarthBundle, type NaturalEarthBundle } from '../api/natural-earth-loader'
import {
  countryPropertiesToSummary,
  type MapInteractionHandlers,
  type MapRenderer,
  type MapRendererCapabilities,
  type MapRenderState,
} from '../model/map-renderer'
import {
  drawEqualEarthCanvas,
  drawEqualEarthOverlayLabels,
  drawEqualEarthSvgVectors,
} from './equal-earth-draw'
import {
  applyEqualEarthZoom,
  buildEqualEarthProjection,
  clampEqualEarthCamera,
  computeBaseScale,
  invertEqualEarthPoint,
  mapZoomToScaleFactor,
  scaleFactorToMapZoom,
  type EqualEarthCamera,
} from './equal-earth-viewport'
import { loadGibs500mOverview, type CachedGibsRaster } from './gibs-overview-loader'

const SVG_NS = 'http://www.w3.org/2000/svg'

export class EqualEarthRenderer implements MapRenderer {
  readonly id = 'equal-earth-renderer'
  readonly capabilities: MapRendererCapabilities = {
    supportsDeckGl: false,
    supports3dGlobe: false,
    supportsRasterTiles: false,
    supportsAntimeridianClipping: true,
  }

  private wrapperEl: HTMLDivElement | null = null
  private canvasEl: HTMLCanvasElement | null = null
  private svgEl: SVGSVGElement | null = null
  private labelsEl: HTMLDivElement | null = null
  private resizeObserver: ResizeObserver | null = null
  private bundle: NaturalEarthBundle | null = null
  private state: MapRenderState | null = null
  private handlers: MapInteractionHandlers
  private camera: EqualEarthCamera = { width: 960, height: 560, baseScale: 180, scaleFactor: 1, panX: 0, panY: 0 }
  private isDragging = false
  private dragMoved = false
  private pointerDownPos: [number, number] | null = null
  private lastPointerPos: [number, number] | null = null
  private loadedBasemapRasters = new Map<BasemapId, CachedGibsRaster | null>()
  private cachedCanvasRenderKey = ''
  private destroyed = false

  private boundPointerDown = (e: PointerEvent) => this.handlePointerDown(e)
  private boundPointerMove = (e: PointerEvent) => this.handlePointerMove(e)
  private boundPointerUp = (e: PointerEvent) => this.handlePointerUp(e)
  private boundPointerLeave = () => this.handlePointerLeave()
  private boundWheel = (e: WheelEvent) => this.handleWheel(e)
  private boundDblClick = (e: MouseEvent) => this.handleDoubleClick(e)

  constructor(handlers: MapInteractionHandlers) {
    this.handlers = handlers
  }

  mount(container: HTMLElement): void {
    this.destroyed = false
    const wrapper = document.createElement('div')
    wrapper.className = 'equal-earth-stage'
    Object.assign(wrapper.style, {
      position: 'relative',
      width: '100%',
      height: '100%',
      overflow: 'hidden',
      touchAction: 'none',
      userSelect: 'none',
    })

    const canvas = document.createElement('canvas')
    canvas.className = 'equal-earth-stage__canvas'
    Object.assign(canvas.style, { position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block' })

    const svg = document.createElementNS(SVG_NS, 'svg')
    svg.setAttribute('class', 'equal-earth-stage__svg')
    Object.assign(svg.style, { position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block' })

    const labels = document.createElement('div')
    labels.className = 'equal-earth-stage__labels'
    Object.assign(labels.style, { position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'hidden' })

    wrapper.append(canvas, svg, labels)
    container.appendChild(wrapper)

    this.wrapperEl = wrapper
    this.canvasEl = canvas
    this.svgEl = svg
    this.labelsEl = labels

    wrapper.addEventListener('pointerdown', this.boundPointerDown)
    wrapper.addEventListener('pointermove', this.boundPointerMove)
    wrapper.addEventListener('pointerup', this.boundPointerUp)
    wrapper.addEventListener('pointerleave', this.boundPointerLeave)
    wrapper.addEventListener('wheel', this.boundWheel, { passive: false })
    wrapper.addEventListener('dblclick', this.boundDblClick)

    this.measureContainer()
    this.resizeObserver = new ResizeObserver(() => {
      this.measureContainer()
      this.render()
    })
    this.resizeObserver.observe(wrapper)

    loadNaturalEarthBundle()
      .then((bundle) => {
        if (this.destroyed) return
        this.bundle = bundle
        this.handlers.onRendererStatus?.({ ready: true, error: null, deckGlActive: false, warning: null })
        this.render()
      })
      .catch((err: unknown) => {
        if (this.destroyed) return
        const msg = err instanceof Error ? err.message : 'Failed to load Natural Earth vectors'
        this.handlers.onRendererStatus?.({ ready: false, error: msg, deckGlActive: false, warning: null })
      })
  }

  update(state: MapRenderState): void {
    const prevBasemap = this.state?.basemap
    this.state = state

    if (prevBasemap !== state.basemap) {
      const basemapConfig = BASEMAP_PROVIDER_REGISTRY[state.basemap]
      if (basemapConfig.gibsLayerId && !basemapConfig.supportsTemporalTime && !this.loadedBasemapRasters.has(state.basemap)) {
        loadGibs500mOverview(state.basemap).then((raster) => {
          if (this.destroyed) return
          this.loadedBasemapRasters.set(state.basemap, raster)
          this.render()
        })
      }
    }
    this.render()
  }

  setViewport(viewport: MapViewportState): void {
    const scaleFactor = mapZoomToScaleFactor(viewport.zoom)
    const baseProj = buildEqualEarthProjection(this.camera, true)
    const projected = baseProj(viewport.center)
    const panX = projected ? (this.camera.width / 2 - projected[0]) * scaleFactor : 0
    const panY = projected ? (this.camera.height / 2 - projected[1]) * scaleFactor : 0
    this.camera = clampEqualEarthCamera({ ...this.camera, scaleFactor, panX, panY })
    this.render()
  }

  zoomIn(): void {
    this.zoomAt(1.4, this.camera.width / 2, this.camera.height / 2)
  }

  zoomOut(): void {
    this.zoomAt(1 / 1.4, this.camera.width / 2, this.camera.height / 2)
  }

  resetView(): void {
    this.camera = { ...this.camera, scaleFactor: 1, panX: 0, panY: 0 }
    this.render()
    this.emitViewportChange()
  }

  flyTo(center: [number, number], zoom = 2.6): void {
    this.setViewport({ center, zoom, bearing: 0, pitch: 0 })
    this.emitViewportChange()
  }

  destroy(): void {
    this.destroyed = true
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    if (this.wrapperEl) {
      this.wrapperEl.removeEventListener('pointerdown', this.boundPointerDown)
      this.wrapperEl.removeEventListener('pointermove', this.boundPointerMove)
      this.wrapperEl.removeEventListener('pointerup', this.boundPointerUp)
      this.wrapperEl.removeEventListener('pointerleave', this.boundPointerLeave)
      this.wrapperEl.removeEventListener('wheel', this.boundWheel)
      this.wrapperEl.removeEventListener('dblclick', this.boundDblClick)
      this.wrapperEl.remove()
    }
    this.wrapperEl = null
    this.canvasEl = null
    this.svgEl = null
    this.labelsEl = null
  }

  private measureContainer(): void {
    if (!this.wrapperEl) return
    const rect = this.wrapperEl.getBoundingClientRect()
    const width = Math.max(240, Math.round(rect.width))
    const height = Math.max(200, Math.round(rect.height))
    this.camera = clampEqualEarthCamera({
      ...this.camera,
      width,
      height,
      baseScale: computeBaseScale(width, height),
    })
  }

  private zoomAt(factor: number, anchorX: number, anchorY: number): void {
    const next = applyEqualEarthZoom(this.camera, factor, anchorX, anchorY)
    if (!next) return
    this.camera = next
    this.render()
    this.emitViewportChange()
  }

  private emitViewportChange(): void {
    const proj = buildEqualEarthProjection(this.camera)
    const center = proj.invert?.([this.camera.width / 2, this.camera.height / 2])
    if (!center) return
    this.handlers.onViewportChange?.({
      center: [normalizeLongitude(center[0]), clampLatitude(center[1])],
      zoom: scaleFactorToMapZoom(this.camera.scaleFactor),
      bearing: 0,
      pitch: 0,
    })
  }

  private getLocalPoint(e: { clientX: number; clientY: number }): [number, number] | null {
    if (!this.wrapperEl) return null
    const rect = this.wrapperEl.getBoundingClientRect()
    return [e.clientX - rect.left, e.clientY - rect.top]
  }

  private handlePointerDown(e: PointerEvent): void {
    if (e.button !== 0) return
    const pt = this.getLocalPoint(e)
    if (!pt) return
    this.isDragging = true
    this.dragMoved = false
    this.pointerDownPos = pt
    this.lastPointerPos = pt
    this.wrapperEl?.setPointerCapture(e.pointerId)
  }

  private handlePointerMove(e: PointerEvent): void {
    const pt = this.getLocalPoint(e)
    if (!pt) return
    if (this.isDragging && this.lastPointerPos && this.pointerDownPos) {
      const dx = pt[0] - this.lastPointerPos[0]
      const dy = pt[1] - this.lastPointerPos[1]
      const tdx = pt[0] - this.pointerDownPos[0]
      const tdy = pt[1] - this.pointerDownPos[1]
      if (tdx * tdx + tdy * tdy > 16) this.dragMoved = true
      if (this.dragMoved) {
        this.camera = clampEqualEarthCamera({ ...this.camera, panX: this.camera.panX + dx, panY: this.camera.panY + dy })
        this.lastPointerPos = pt
        this.render()
        return
      }
    }

    const geo = invertEqualEarthPoint(this.camera, pt[0], pt[1])
    this.handlers.onHoverCoordinate?.(geo ? { lon: geo[0], lat: geo[1] } : null)
    if (geo && (this.state?.interactionMode === 'draw-polygon' || this.state?.interactionMode === 'draw-rectangle')) {
      this.handlers.onUpdateDraftHover?.(geo)
    } else if (this.state?.draftHoverPoint) {
      this.handlers.onUpdateDraftHover?.(null)
    }

    const iso = e.target instanceof Element ? e.target.getAttribute('data-iso') : null
    const feature = iso && this.bundle ? this.bundle.countries.features.find((f) => f.properties.isoA3 === iso) : undefined
    this.handlers.onHoverCountry?.(feature ? countryPropertiesToSummary(feature.properties) : null)
  }

  private handlePointerUp(e: PointerEvent): void {
    if (!this.isDragging) return
    this.isDragging = false
    try {
      this.wrapperEl?.releasePointerCapture(e.pointerId)
    } catch {
      void 0
    }
    if (this.dragMoved) {
      this.dragMoved = false
      this.render()
      this.emitViewportChange()
      return
    }
    const pt = this.getLocalPoint(e)
    if (!pt) return
    const geo = invertEqualEarthPoint(this.camera, pt[0], pt[1])
    if (!geo) return

    const mode = this.state?.interactionMode ?? 'inspect'
    if (mode === 'draw-polygon') {
      this.handlers.onAddDraftVertex?.(geo[0], geo[1])
      return
    }
    if (mode === 'draw-rectangle') {
      if ((this.state?.draftVertices.length ?? 0) === 0) this.handlers.onAddDraftVertex?.(geo[0], geo[1])
      else this.handlers.onCompleteDraftShape?.(geo[0], geo[1])
      return
    }

    const iso = e.target instanceof Element ? e.target.getAttribute('data-iso') : null
    const feature = iso && this.bundle ? this.bundle.countries.features.find((f) => f.properties.isoA3 === iso) : undefined
    const summary = feature ? countryPropertiesToSummary(feature.properties) : null
    if (summary && feature) {
      this.handlers.onSelectCountry?.(
        summary,
        normalizeAoiGeometry(feature.geometry) ?? undefined,
      )
    }
    if (mode === 'inspect') {
      this.handlers.onInspectPoint?.(geo[0], geo[1])
    }
  }

  private handlePointerLeave(): void {
    this.handlers.onHoverCoordinate?.(null)
    this.handlers.onHoverCountry?.(null)
  }

  private handleWheel(e: WheelEvent): void {
    e.preventDefault()
    const pt = this.getLocalPoint(e)
    if (pt) this.zoomAt(e.deltaY < 0 ? 1.18 : 1 / 1.18, pt[0], pt[1])
  }

  private handleDoubleClick(e: MouseEvent): void {
    const pt = this.getLocalPoint(e)
    if (!pt) return
    if (this.state?.interactionMode === 'draw-polygon') {
      const geo = invertEqualEarthPoint(this.camera, pt[0], pt[1])
      if (geo) this.handlers.onCompleteDraftShape?.(geo[0], geo[1])
      return
    }
    this.zoomAt(1.5, pt[0], pt[1])
  }

  private render(): void {
    if (!this.canvasEl || !this.svgEl || !this.labelsEl || !this.state) return
    const projection = buildEqualEarthProjection(this.camera)
    const pathGen = geoPath(projection)
    const basemap = BASEMAP_PROVIDER_REGISTRY[this.state.basemap]
    const raster = this.loadedBasemapRasters.get(this.state.basemap)
    const step = this.isDragging ? 3 : 2
    const canvasKey = `${this.camera.width}x${this.camera.height}:${this.camera.scaleFactor.toFixed(4)}:${this.camera.panX.toFixed(2)}:${this.camera.panY.toFixed(2)}:${this.state.basemap}:${Boolean(raster)}:${step}`
    if (this.cachedCanvasRenderKey !== canvasKey) {
      this.cachedCanvasRenderKey = canvasKey
      drawEqualEarthCanvas({
        canvas: this.canvasEl,
        width: this.camera.width,
        height: this.camera.height,
        projection,
        pathGen,
        basemap,
        raster,
        step,
      })
    }
    drawEqualEarthSvgVectors({
      svg: this.svgEl,
      state: this.state,
      bundle: this.bundle,
      width: this.camera.width,
      height: this.camera.height,
      projection,
      pathGen,
      basemap,
      hasRasterBasemap: Boolean(raster),
    })
    drawEqualEarthOverlayLabels({
      container: this.labelsEl,
      state: this.state,
      width: this.camera.width,
      height: this.camera.height,
      scaleFactor: this.camera.scaleFactor,
      projection,
      hasRasterBasemap: Boolean(raster),
    })
  }
}
