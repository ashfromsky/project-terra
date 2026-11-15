import type {
  CountrySelectionSummary,
  MapLayerVisibility,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'

export interface CountryFeatureProperties {
  isoA3: string
  name: string
  nameLong: string
  continent: string
  subregion: string
  labelRank: number
  labelLon: number
  labelLat: number
  bbox: [number, number, number, number]
  terraRegion: RegionOption
}

export interface GeographicLabelAnchor {
  id: string
  text: string
  longitude: number
  latitude: number
  kind: 'continent' | 'ocean' | 'equator'
  nodeId?: string
}

export interface CountryLabelAnchor {
  isoA3: string
  name: string
  longitude: number
  latitude: number
  labelRank: number
  terraRegion: RegionOption
}

export interface ProjectedLabelPosition {
  id: string
  text: string
  x: number
  y: number
  visible: boolean
  kind: 'continent' | 'ocean' | 'equator' | 'country'
  nodeId?: string
  isoA3?: string
  isSelected?: boolean
  isHovered?: boolean
}

export interface RegionCameraPreset {
  region: RegionOption
  center: [number, number]
  zoom: number
  bounds?: [[number, number], [number, number]]
}

export interface ThematicScaleStop {
  value: number
  color: string
  rgb: [number, number, number]
}

export interface ThematicLayerDefinition {
  variable: VariableOption
  shortTitle: string
  unit: string
  layerId: string
  minLabel: string
  midLabel: string
  maxLabel: string
  gradientCss: string
  provenanceNote: string
  stops: readonly ThematicScaleStop[]
}

export interface WorldMapController {
  zoomIn: () => void
  zoomOut: () => void
  resetWorldView: () => void
  flyToRegion: (region: RegionOption) => void
  flyToCoordinates: (longitude: number, latitude: number, zoom?: number) => void
  currentZoom: number
  isMapReady: boolean
  projectedGeoLabels: readonly ProjectedLabelPosition[]
  projectedCountryLabels: readonly ProjectedLabelPosition[]
  calloutPixelAnchor: { x: number; y: number } | null
}

export type {
  CountrySelectionSummary,
  MapLayerVisibility,
  RegionOption,
  VariableOption,
}
