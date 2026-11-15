import type { CountrySelectionSummary } from '../../../shared/store/ui-store'
import type {
  AoiFeature,
  BasemapId,
  MapLayerDefinition,
  MapViewportState,
  ProjectionId,
} from '../../../shared/types/geospatial'
import type { CountryFeatureProperties } from '../../../widgets/world-map/model/types'

export type ExplorerInteractionMode =
  | 'inspect'
  | 'select-feature'
  | 'draw-polygon'
  | 'draw-rectangle'

export interface LayerRenderConfig {
  layer: MapLayerDefinition
  visible: boolean
  opacity: number
  minValue: number
  maxValue: number
}

export interface MapRenderState {
  projection: ProjectionId
  basemap: BasemapId
  selectedDate: string
  activeLayer: LayerRenderConfig | null
  showGraticules: boolean
  showBorders: boolean
  showLabels: boolean
  showRegionBoundaries: boolean
  interactionMode: ExplorerInteractionMode
  selectedCountry: CountrySelectionSummary | null
  hoveredCountryIso: string | null
  inspectedPoint: { lon: number; lat: number } | null
  aois: readonly AoiFeature[]
  selectedAoiId: string | null
  draftVertices: readonly [number, number][]
  draftHoverPoint: [number, number] | null
  viewport: MapViewportState
}

export interface MapInteractionHandlers {
  onHoverCoordinate?: (coords: { lon: number; lat: number } | null) => void
  onHoverCountry?: (country: CountrySelectionSummary | null) => void
  onSelectCountry?: (
    country: CountrySelectionSummary | null,
    featureGeometry?: AoiFeature['geometry'],
  ) => void
  onInspectPoint?: (lon: number, lat: number) => void
  onAddDraftVertex?: (lon: number, lat: number) => void
  onCompleteDraftShape?: (lon: number, lat: number) => void
  onUpdateDraftHover?: (point: [number, number] | null) => void
  onSelectAoi?: (aoiId: string) => void
  onViewportChange?: (viewport: MapViewportState) => void
  onRendererStatus?: (status: {
    ready: boolean
    error: string | null
    deckGlActive: boolean
    warning: string | null
  }) => void
}

export interface MapRendererCapabilities {
  supportsDeckGl: boolean
  supports3dGlobe: boolean
  supportsRasterTiles: boolean
  supportsAntimeridianClipping: boolean
}

export interface MapRenderer {
  readonly id: string
  readonly capabilities: MapRendererCapabilities
  mount(container: HTMLElement): void
  update(state: MapRenderState): void
  setViewport(viewport: MapViewportState, animate?: boolean): void
  zoomIn(): void
  zoomOut(): void
  resetView(): void
  flyTo(center: [number, number], zoom?: number): void
  destroy(): void
}

export function countryPropertiesToSummary(
  props: Partial<CountryFeatureProperties> | null | undefined,
): CountrySelectionSummary | null {
  if (!props || typeof props.isoA3 !== 'string') {
    return null
  }
  return {
    isoA3: props.isoA3,
    name: typeof props.name === 'string' ? props.name : props.isoA3,
    continent: typeof props.continent === 'string' ? props.continent : 'Global',
    subregion: typeof props.subregion === 'string' ? props.subregion : 'Global',
    terraRegion: props.terraRegion ?? 'Global land',
    centerLon: Number(props.labelLon ?? 0),
    centerLat: Number(props.labelLat ?? 0),
  }
}
