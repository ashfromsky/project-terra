import { create } from 'zustand'
import {
  assignAoiRoleInList,
  buildCountryAoi,
  buildDraftCompletionAoi,
  mergeRoleExclusiveAoi,
} from './explore-aoi-helpers'
import {
  DEFAULT_VIEWPORT,
  resolveLayerControlState,
  type ComparisonPaneConfig,
  type ExploreState,
  type LayerControlState,
} from './explore-store.types'

export type { ComparisonPaneConfig, ExploreState, LayerControlState }
export { DEFAULT_VIEWPORT, resolveLayerControlState }

function isWideWorkspaceViewport(): boolean {
  if (typeof window === 'undefined') return true
  return window.innerWidth >= 1200
}

export const useExploreStore = create<ExploreState>()((set, get) => ({
  projection: 'mercator',
  setProjection: (projection) => set({ projection }),

  basemap: 'scientific-light',
  setBasemap: (basemap) => set({ basemap }),

  primaryLayerId: 'ndvi-mod13q1',
  setPrimaryLayerId: (layerId) =>
    set((state) => ({
      primaryLayerId: layerId,
      layerStates: {
        ...state.layerStates,
        [layerId]: { ...state.layerStates[layerId], visible: true },
      },
    })),

  layerStates: {},

  toggleLayerVisibility: (layerId) =>
    set((state) => {
      const current = state.layerStates[layerId]
      const currentVisible = current?.visible ?? layerId === state.primaryLayerId
      const nextVisible = !currentVisible
      return {
        primaryLayerId: nextVisible ? layerId : state.primaryLayerId,
        layerStates: { ...state.layerStates, [layerId]: { ...current, visible: nextVisible } },
      }
    }),

  setLayerOpacity: (layerId, opacity) =>
    set((state) => {
      const current = state.layerStates[layerId]
      return {
        layerStates: {
          ...state.layerStates,
          [layerId]: { ...current, opacity: Math.max(0, Math.min(1, opacity)) },
        },
      }
    }),

  setLayerValueRange: (layerId, minValue, maxValue) =>
    set((state) => {
      const current = state.layerStates[layerId]
      return {
        layerStates: {
          ...state.layerStates,
          [layerId]: {
            ...current,
            minValue: Math.min(minValue, maxValue),
            maxValue: Math.max(minValue, maxValue),
          },
        },
      }
    }),

  resetLayerValueRange: (layerId) =>
    set((state) => {
      const current = state.layerStates[layerId]
      if (!current) return state
      const nextOverride: Partial<LayerControlState> = { ...current }
      delete nextOverride.minValue
      delete nextOverride.maxValue
      return {
        layerStates: {
          ...state.layerStates,
          [layerId]: nextOverride,
        },
      }
    }),

  selectedDate: '2025-12-01',
  setSelectedDate: (selectedDate) => set({ selectedDate }),
  dateRangeStart: '2020-01-01',
  dateRangeEnd: '2025-12-01',
  setDateRange: (dateRangeStart, dateRangeEnd) =>
    set({
      dateRangeStart: dateRangeStart <= dateRangeEnd ? dateRangeStart : dateRangeEnd,
      dateRangeEnd: dateRangeStart <= dateRangeEnd ? dateRangeEnd : dateRangeStart,
    }),
  temporalPlaying: false,
  setTemporalPlaying: (temporalPlaying) => set({ temporalPlaying }),
  toggleTemporalPlaying: () => set((state) => ({ temporalPlaying: !state.temporalPlaying })),
  temporalCadence: 'monthly',
  setTemporalCadence: (temporalCadence) => set({ temporalCadence }),

  interactionMode: 'inspect',
  setInteractionMode: (interactionMode) =>
    set((state) => ({
      interactionMode,
      draftVertices: [],
      draftHoverPoint: null,
      inspectorTab:
        interactionMode === 'draw-polygon' || interactionMode === 'draw-rectangle'
          ? 'aoi'
          : interactionMode === 'select-feature'
            ? 'feature'
            : state.inspectorTab,
    })),

  hoverCoordinate: null,
  setHoverCoordinate: (hoverCoordinate) => set({ hoverCoordinate }),
  hoveredCountry: null,
  setHoveredCountry: (hoveredCountry) => set({ hoveredCountry }),
  selectedCountry: null,
  setSelectedCountry: (selectedCountry) =>
    set((state) => ({
      selectedCountry,
      inspectorTab:
        selectedCountry && state.interactionMode === 'select-feature'
          ? 'feature'
          : state.inspectorTab,
    })),
  inspectedPoint: null,
  setInspectedPoint: (inspectedPoint) =>
    set((state) => ({
      inspectedPoint,
      rightInspectorOpen: inspectedPoint ? true : state.rightInspectorOpen,
      inspectorTab: inspectedPoint ? 'point' : state.inspectorTab,
    })),

  aois: [],
  selectedAoiId: null,
  setSelectedAoiId: (selectedAoiId) => set({ selectedAoiId }),
  activeAoiRole: 'regionA',
  setActiveAoiRole: (activeAoiRole) => set({ activeAoiRole }),
  aoiSyncError: null,
  setAoiSyncError: (aoiSyncError) => set({ aoiSyncError }),
  aoiSyncPending: false,
  setAoiSyncPending: (aoiSyncPending) => set({ aoiSyncPending }),
  draftVertices: [],
  draftHoverPoint: null,

  addDraftVertex: (lon, lat) =>
    set((state) => ({ draftVertices: [...state.draftVertices, [lon, lat]] })),

  setDraftHoverPoint: (draftHoverPoint) => set({ draftHoverPoint }),

  completeDraftAoi: (lon, lat) => {
    const state = get()
    const feature = buildDraftCompletionAoi({
      interactionMode: state.interactionMode,
      draftVertices: state.draftVertices,
      activeAoiRole: state.activeAoiRole,
      lon,
      lat,
    })
    if (!feature) return
    set({
      aois: mergeRoleExclusiveAoi(state.aois, feature),
      selectedAoiId: feature.properties.id,
      draftVertices: [],
      draftHoverPoint: null,
      interactionMode: 'inspect',
      rightInspectorOpen: true,
    })
  },

  cancelDraftAoi: () =>
    set({ draftVertices: [], draftHoverPoint: null, interactionMode: 'inspect' }),

  addCountryAsAoi: (country, geometry, roleOverride) =>
    set((state) => {
      const feature = buildCountryAoi(country, geometry, roleOverride ?? state.activeAoiRole)
      return {
        aois: mergeRoleExclusiveAoi(state.aois, feature),
        selectedAoiId: feature.properties.id,
        rightInspectorOpen: true,
      }
    }),

  updateAoiRole: (aoiId, role) =>
    set((state) => ({ aois: assignAoiRoleInList(state.aois, aoiId, role) })),

  renameAoi: (aoiId, name) =>
    set((state) => ({
      aois: state.aois.map((aoi) =>
        aoi.properties.id === aoiId ? { ...aoi, properties: { ...aoi.properties, name } } : aoi,
      ),
    })),

  removeAoi: (aoiId) =>
    set((state) => ({
      aois: state.aois.filter((aoi) => aoi.properties.id !== aoiId),
      selectedAoiId: state.selectedAoiId === aoiId ? null : state.selectedAoiId,
    })),

  clearAois: () => set({ aois: [], selectedAoiId: null }),

  comparisonMode: false,
  setComparisonMode: (comparisonMode) => set({ comparisonMode }),
  syncCameras: true,
  setSyncCameras: (syncCameras) => set({ syncCameras }),
  comparisonLeft: {
    layerId: 'ndvi-mod13q1',
    date: '2020-07-01',
    basemap: 'scientific-light',
    opacity: 0.85,
  },
  comparisonRight: {
    layerId: 'lst-anomaly',
    date: '2025-07-01',
    basemap: 'scientific-light',
    opacity: 0.85,
  },
  setComparisonLeft: (patch) =>
    set((state) => ({ comparisonLeft: { ...state.comparisonLeft, ...patch } })),
  setComparisonRight: (patch) =>
    set((state) => ({ comparisonRight: { ...state.comparisonRight, ...patch } })),

  showGraticules: true,
  setShowGraticules: (showGraticules) => set({ showGraticules }),
  showBorders: true,
  setShowBorders: (showBorders) => set({ showBorders }),
  showLabels: true,
  setShowLabels: (showLabels) => set({ showLabels }),
  showRegionBoundaries: false,
  setShowRegionBoundaries: (showRegionBoundaries) => set({ showRegionBoundaries }),

  leftSidebarOpen: isWideWorkspaceViewport(),
  setLeftSidebarOpen: (leftSidebarOpen) =>
    set((state) => ({
      leftSidebarOpen,
      rightInspectorOpen:
        leftSidebarOpen && !isWideWorkspaceViewport() ? false : state.rightInspectorOpen,
    })),
  rightInspectorOpen: isWideWorkspaceViewport(),
  setRightInspectorOpen: (rightInspectorOpen) =>
    set((state) => ({
      rightInspectorOpen,
      leftSidebarOpen:
        rightInspectorOpen && !isWideWorkspaceViewport() ? false : state.leftSidebarOpen,
    })),
  inspectorTab: 'point',
  setInspectorTab: (inspectorTab) => set({ inspectorTab }),
  bottomPanelOpen: true,
  setBottomPanelOpen: (bottomPanelOpen) => set({ bottomPanelOpen }),
  isFullscreen: false,
  setIsFullscreen: (isFullscreen) => set({ isFullscreen }),

  viewport: DEFAULT_VIEWPORT,
  setViewport: (viewport) => set({ viewport }),

  rendererStatus: { ready: false, error: null, deckGlActive: false, warning: null },
  setRendererStatus: (rendererStatus) => set({ rendererStatus }),
}))
