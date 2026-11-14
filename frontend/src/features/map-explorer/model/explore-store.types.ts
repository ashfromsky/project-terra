import { ENVIRONMENTAL_LAYER_CATALOG } from '../../../entities/layer/model/layer-catalog'
import type { ExplorerInteractionMode } from '../../../entities/map/model/map-renderer'
import type { CountrySelectionSummary } from '../../../shared/store/ui-store'
import type {
  AoiFeature,
  AoiGeometry,
  AoiRole,
  BasemapId,
  MapViewportState,
  ObservationGranularity,
  ProjectionId,
} from '../../../shared/types/geospatial'

export interface LayerControlState {
  visible: boolean
  opacity: number
  minValue: number
  maxValue: number
}

export interface ComparisonPaneConfig {
  layerId: string
  date: string
  basemap: BasemapId
  opacity: number
}

export const DEFAULT_LAYER_STATES: Record<string, LayerControlState> = Object.fromEntries(
  ENVIRONMENTAL_LAYER_CATALOG.map((layer) => [
    layer.id,
    {
      visible: layer.id === 'ndvi-mod13q1',
      opacity: 0.85,
      minValue: layer.valueRange.defaultMin,
      maxValue: layer.valueRange.defaultMax,
    },
  ]),
)

export const DEFAULT_VIEWPORT: MapViewportState = {
  center: [10, 18],
  zoom: 0.65,
  bearing: 0,
  pitch: 0,
}

export interface ExploreState {
  projection: ProjectionId
  setProjection: (projection: ProjectionId) => void
  basemap: BasemapId
  setBasemap: (basemap: BasemapId) => void
  primaryLayerId: string
  setPrimaryLayerId: (layerId: string) => void
  layerStates: Record<string, LayerControlState>
  toggleLayerVisibility: (layerId: string) => void
  setLayerOpacity: (layerId: string, opacity: number) => void
  setLayerValueRange: (layerId: string, minValue: number, maxValue: number) => void
  resetLayerValueRange: (layerId: string) => void
  syntheticPreviewEnabled: boolean
  setSyntheticPreviewEnabled: (enabled: boolean) => void
  selectedDate: string
  setSelectedDate: (date: string) => void
  dateRangeStart: string
  dateRangeEnd: string
  setDateRange: (start: string, end: string) => void
  temporalPlaying: boolean
  setTemporalPlaying: (playing: boolean) => void
  toggleTemporalPlaying: () => void
  temporalCadence: ObservationGranularity
  setTemporalCadence: (cadence: ObservationGranularity) => void
  interactionMode: ExplorerInteractionMode
  setInteractionMode: (mode: ExplorerInteractionMode) => void
  hoverCoordinate: { lon: number; lat: number } | null
  setHoverCoordinate: (coords: { lon: number; lat: number } | null) => void
  hoveredCountry: CountrySelectionSummary | null
  setHoveredCountry: (country: CountrySelectionSummary | null) => void
  selectedCountry: CountrySelectionSummary | null
  setSelectedCountry: (country: CountrySelectionSummary | null) => void
  inspectedPoint: { lon: number; lat: number } | null
  setInspectedPoint: (point: { lon: number; lat: number } | null) => void
  aois: AoiFeature[]
  selectedAoiId: string | null
  setSelectedAoiId: (id: string | null) => void
  activeAoiRole: AoiRole
  setActiveAoiRole: (role: AoiRole) => void
  draftVertices: [number, number][]
  draftHoverPoint: [number, number] | null
  addDraftVertex: (lon: number, lat: number) => void
  setDraftHoverPoint: (point: [number, number] | null) => void
  completeDraftAoi: (lon?: number, lat?: number) => void
  cancelDraftAoi: () => void
  addCountryAsAoi: (
    country: CountrySelectionSummary,
    geometry: AoiGeometry,
    role?: AoiRole,
  ) => void
  updateAoiRole: (aoiId: string, role: AoiRole) => void
  renameAoi: (aoiId: string, name: string) => void
  removeAoi: (aoiId: string) => void
  clearAois: () => void
  comparisonMode: boolean
  setComparisonMode: (enabled: boolean) => void
  syncCameras: boolean
  setSyncCameras: (sync: boolean) => void
  comparisonLeft: ComparisonPaneConfig
  comparisonRight: ComparisonPaneConfig
  setComparisonLeft: (patch: Partial<ComparisonPaneConfig>) => void
  setComparisonRight: (patch: Partial<ComparisonPaneConfig>) => void
  showGraticules: boolean
  setShowGraticules: (show: boolean) => void
  showBorders: boolean
  setShowBorders: (show: boolean) => void
  showLabels: boolean
  setShowLabels: (show: boolean) => void
  showRegionBoundaries: boolean
  setShowRegionBoundaries: (show: boolean) => void
  leftSidebarOpen: boolean
  setLeftSidebarOpen: (open: boolean) => void
  rightInspectorOpen: boolean
  setRightInspectorOpen: (open: boolean) => void
  inspectorTab: 'point' | 'feature' | 'aoi'
  setInspectorTab: (tab: 'point' | 'feature' | 'aoi') => void
  bottomPanelOpen: boolean
  setBottomPanelOpen: (open: boolean) => void
  isFullscreen: boolean
  setIsFullscreen: (fullscreen: boolean) => void
  viewport: MapViewportState
  setViewport: (viewport: MapViewportState) => void
  rendererStatus: {
    ready: boolean
    error: string | null
    deckGlActive: boolean
    warning: string | null
  }
  setRendererStatus: (status: {
    ready: boolean
    error: string | null
    deckGlActive: boolean
    warning: string | null
  }) => void
}
