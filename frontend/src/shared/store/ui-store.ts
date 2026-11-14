import { create } from 'zustand'

export type VariableOption =
  | 'Land surface temperature'
  | 'Vegetation index (NDVI)'
  | 'Enhanced vegetation (EVI)'
  | 'Precipitation anomaly'

export type RegionOption =
  | 'Global land'
  | 'Amazon basin'
  | 'Sahel belt'
  | 'Siberian boreal'
  | 'Mediterranean basin'
  | 'Australian outback'

export type WorkspaceTab = 'Overview' | 'Regional comparison' | 'Methods & quality'

export type MapToolId =
  | 'layers'
  | 'region-selection'
  | 'locate'
  | 'zoom-in'
  | 'zoom-out'
  | 'fullscreen'

export type TemporalCadence = 'Monthly' | 'Seasonal' | 'Annual'

interface UiState {
  panelOpen: boolean
  togglePanel: () => void
  setPanelOpen: (open: boolean) => void
  selectedVariable: VariableOption
  setSelectedVariable: (variable: VariableOption) => void
  selectedRegion: RegionOption
  setSelectedRegion: (region: RegionOption) => void
  activeWorkspaceTab: WorkspaceTab
  setActiveWorkspaceTab: (tab: WorkspaceTab) => void
  activeMapTool: MapToolId
  setActiveMapTool: (tool: MapToolId) => void
  selectedHotspotId: string
  setSelectedHotspotId: (id: string) => void
  timelinePlaying: boolean
  toggleTimelinePlaying: () => void
  temporalCadence: TemporalCadence
  setTemporalCadence: (cadence: TemporalCadence) => void
  searchQuery: string
  setSearchQuery: (query: string) => void
  mobileNavOpen: boolean
  setMobileNavOpen: (open: boolean) => void
}

export const useUiStore = create<UiState>()((set) => ({
  panelOpen: true,
  togglePanel: () => set((state) => ({ panelOpen: !state.panelOpen })),
  setPanelOpen: (open) => set({ panelOpen: open }),
  selectedVariable: 'Land surface temperature',
  setSelectedVariable: (selectedVariable) => set({ selectedVariable }),
  selectedRegion: 'Global land',
  setSelectedRegion: (selectedRegion) => set({ selectedRegion }),
  activeWorkspaceTab: 'Overview',
  setActiveWorkspaceTab: (activeWorkspaceTab) => set({ activeWorkspaceTab }),
  activeMapTool: 'layers',
  setActiveMapTool: (activeMapTool) => set({ activeMapTool }),
  selectedHotspotId: 'amazon',
  setSelectedHotspotId: (selectedHotspotId) => set({ selectedHotspotId }),
  timelinePlaying: false,
  toggleTimelinePlaying: () =>
    set((state) => ({ timelinePlaying: !state.timelinePlaying })),
  temporalCadence: 'Monthly',
  setTemporalCadence: (temporalCadence) => set({ temporalCadence }),
  searchQuery: '',
  setSearchQuery: (searchQuery) => set({ searchQuery }),
  mobileNavOpen: false,
  setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen }),
}))
