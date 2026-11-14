import { useEffect, useImperativeHandle, useRef, type Ref } from 'react'
import { MapProjectionController } from '../../../entities/map/lib/map-projection-controller'
import type { MapRenderState } from '../../../entities/map/model/map-renderer'
import type { MapViewportState } from '../../../shared/types/geospatial'
import type { CountrySelectionSummary } from '../../../shared/store/ui-store'
import type { AoiGeometry } from '../../../shared/types/geospatial'

export interface ExplorerMapViewportHandle {
  zoomIn: () => void
  zoomOut: () => void
  resetView: () => void
  flyTo: (center: [number, number], zoom?: number) => void
  setViewport: (viewport: MapViewportState, animate?: boolean) => void
}

export interface ExplorerMapViewportProps {
  ref?: Ref<ExplorerMapViewportHandle>
  renderState: MapRenderState
  onHoverCoordinate?: (coords: { lon: number; lat: number } | null) => void
  onHoverCountry?: (country: CountrySelectionSummary | null) => void
  onSelectCountry?: (
    country: CountrySelectionSummary | null,
    geometry?: AoiGeometry,
  ) => void
  onInspectPoint?: (lon: number, lat: number) => void
  onAddDraftVertex?: (lon: number, lat: number) => void
  onCompleteDraftShape?: (lon: number, lat: number) => void
  onUpdateDraftHover?: (point: [number, number] | null) => void
  onViewportChange?: (viewport: MapViewportState) => void
  onRendererStatus?: (status: {
    ready: boolean
    error: string | null
    deckGlActive: boolean
    warning: string | null
  }) => void
  ariaLabel?: string
}

export function ExplorerMapViewport({
  ref,
  renderState,
  onHoverCoordinate,
  onHoverCountry,
  onSelectCountry,
  onInspectPoint,
  onAddDraftVertex,
  onCompleteDraftShape,
  onUpdateDraftHover,
  onViewportChange,
  onRendererStatus,
  ariaLabel = 'Interactive geospatial map canvas',
}: ExplorerMapViewportProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const controllerRef = useRef<MapProjectionController | null>(null)

  const callbacksRef = useRef({
    onHoverCoordinate,
    onHoverCountry,
    onSelectCountry,
    onInspectPoint,
    onAddDraftVertex,
    onCompleteDraftShape,
    onUpdateDraftHover,
    onViewportChange,
    onRendererStatus,
  })

  useEffect(() => {
    callbacksRef.current = {
      onHoverCoordinate,
      onHoverCountry,
      onSelectCountry,
      onInspectPoint,
      onAddDraftVertex,
      onCompleteDraftShape,
      onUpdateDraftHover,
      onViewportChange,
      onRendererStatus,
    }
  }, [
    onAddDraftVertex,
    onCompleteDraftShape,
    onHoverCoordinate,
    onHoverCountry,
    onInspectPoint,
    onRendererStatus,
    onSelectCountry,
    onUpdateDraftHover,
    onViewportChange,
  ])

  const initialRenderStateRef = useRef(renderState)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const controller = new MapProjectionController({
      onHoverCoordinate: (coords) => callbacksRef.current.onHoverCoordinate?.(coords),
      onHoverCountry: (country) => callbacksRef.current.onHoverCountry?.(country),
      onSelectCountry: (country, geometry) =>
        callbacksRef.current.onSelectCountry?.(country, geometry),
      onInspectPoint: (lon, lat) => callbacksRef.current.onInspectPoint?.(lon, lat),
      onAddDraftVertex: (lon, lat) => callbacksRef.current.onAddDraftVertex?.(lon, lat),
      onCompleteDraftShape: (lon, lat) =>
        callbacksRef.current.onCompleteDraftShape?.(lon, lat),
      onUpdateDraftHover: (point) => callbacksRef.current.onUpdateDraftHover?.(point),
      onViewportChange: (vp) => callbacksRef.current.onViewportChange?.(vp),
      onRendererStatus: (st) => callbacksRef.current.onRendererStatus?.(st),
    })

    controllerRef.current = controller
    controller.mount(container, initialRenderStateRef.current)

    return () => {
      controller.destroy()
      controllerRef.current = null
    }
  }, [])

  useEffect(() => {
    controllerRef.current?.update(renderState)
  }, [renderState])

  useImperativeHandle(
    ref,
    () => ({
      zoomIn: () => controllerRef.current?.zoomIn(),
      zoomOut: () => controllerRef.current?.zoomOut(),
      resetView: () => controllerRef.current?.resetView(),
      flyTo: (center, zoom) => controllerRef.current?.flyTo(center, zoom),
      setViewport: (viewport, animate) =>
        controllerRef.current?.setViewport(viewport, animate),
    }),
    [],
  )

  return (
    <div
      ref={containerRef}
      className="explorer-map-viewport"
      role="region"
      aria-label={ariaLabel}
    />
  )
}
