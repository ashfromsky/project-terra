import type { ExplorerInteractionMode } from '../../../entities/map/model/map-renderer'
import {
  BASEMAP_LIST,
  BASEMAP_PROVIDER_REGISTRY,
  PROJECTION_REGISTRY,
} from '../../../shared/config/geospatial'
import type { BasemapId, ProjectionId } from '../../../shared/types/geospatial'
import {
  Calendar,
  Columns2,
  Compass,
  Crosshair,
  Globe,
  Layers,
  MapIcon,
  Maximize2,
  Minimize2,
  MousePointerClick,
  PanelRight,
  Pentagon,
  RotateCcw,
  Square,
} from '../../../shared/ui/explorer-icons'
import { useExploreStore } from '../model/use-explore-store'
import { ExplorerSearchBox } from './ExplorerSearchBox'

const PROJECTION_ORDER: readonly ProjectionId[] = ['equal-earth', 'globe', 'mercator']

const TOOL_BUTTONS: readonly {
  id: ExplorerInteractionMode
  label: string
  title: string
  icon: typeof Crosshair
}[] = [
  {
    id: 'inspect',
    label: 'Inspect',
    title: 'Inspect WGS 84 coordinates and layer metadata',
    icon: Crosshair,
  },
  {
    id: 'select-feature',
    label: 'Select',
    title: 'Select geographic boundary features',
    icon: MousePointerClick,
  },
  {
    id: 'draw-polygon',
    label: 'Polygon',
    title: 'Draw custom WGS 84 polygon Area of Interest',
    icon: Pentagon,
  },
  {
    id: 'draw-rectangle',
    label: 'Rectangle',
    title: 'Draw bounding rectangle Area of Interest',
    icon: Square,
  },
]

function isBasemapCompatible(basemapId: BasemapId, projId: ProjectionId): boolean {
  const cfg = BASEMAP_PROVIDER_REGISTRY[basemapId]
  if (projId === 'equal-earth') return cfg.supportsEqualEarth
  if (projId === 'globe') return cfg.supportsGlobe
  return cfg.supportsMercator
}

export interface ExplorerTopToolbarProps {
  onFlyTo: (center: [number, number], zoom?: number) => void
  onResetView: () => void
}

export function ExplorerTopToolbar({
  onFlyTo,
  onResetView,
}: ExplorerTopToolbarProps) {
  const projection = useExploreStore((s) => s.projection)
  const setProjection = useExploreStore((s) => s.setProjection)
  const basemap = useExploreStore((s) => s.basemap)
  const setBasemap = useExploreStore((s) => s.setBasemap)
  const selectedDate = useExploreStore((s) => s.selectedDate)
  const setSelectedDate = useExploreStore((s) => s.setSelectedDate)
  const gibsLayerId = useExploreStore((s) => s.gibsLayerId)
  const gibsDate = useExploreStore((s) => s.gibsDate)
  const setGibsDate = useExploreStore((s) => s.setGibsDate)
  const displayDate = gibsLayerId ? gibsDate : selectedDate
  const interactionMode = useExploreStore((s) => s.interactionMode)
  const setInteractionMode = useExploreStore((s) => s.setInteractionMode)
  const comparisonMode = useExploreStore((s) => s.comparisonMode)
  const setComparisonMode = useExploreStore((s) => s.setComparisonMode)
  const leftSidebarOpen = useExploreStore((s) => s.leftSidebarOpen)
  const setLeftSidebarOpen = useExploreStore((s) => s.setLeftSidebarOpen)
  const rightInspectorOpen = useExploreStore((s) => s.rightInspectorOpen)
  const setRightInspectorOpen = useExploreStore((s) => s.setRightInspectorOpen)
  const isFullscreen = useExploreStore((s) => s.isFullscreen)
  const setIsFullscreen = useExploreStore((s) => s.setIsFullscreen)

  const activeProjectionDef = PROJECTION_REGISTRY[projection]

  return (
    <header className="explorer-toolbar" role="region" aria-label="Map explorer controls">
      <div className="explorer-toolbar__group explorer-toolbar__group--left">
        <button
          type="button"
          className={`explorer-icon-btn ${leftSidebarOpen ? 'is-active' : ''}`}
          onClick={() => setLeftSidebarOpen(!leftSidebarOpen)}
          aria-pressed={leftSidebarOpen}
          aria-label="Toggle environmental layers sidebar"
          title="Toggle layers catalog"
        >
          <Layers size={16} />
          <span className="explorer-btn-label-desktop">Layers</span>
        </button>

        <ExplorerSearchBox onFlyTo={onFlyTo} />
      </div>

      <div className="explorer-toolbar__group explorer-toolbar__group--center">
        <div
          className="explorer-segmented"
          role="radiogroup"
          aria-label="Cartographic projection"
        >
          {PROJECTION_ORDER.map((id) => {
            const def = PROJECTION_REGISTRY[id]
            const active = projection === id
            return (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={active}
                className={`explorer-segmented__btn ${active ? 'is-active' : ''}`}
                onClick={() => setProjection(id)}
                title={`${def.label} (${def.epsgOrName}): ${def.scientificSuitability}`}
              >
                {id === 'globe' ? (
                  <Globe size={13} aria-hidden="true" />
                ) : id === 'mercator' ? (
                  <MapIcon size={13} aria-hidden="true" />
                ) : (
                  <Compass size={13} aria-hidden="true" />
                )}
                <span>{def.shortLabel}</span>
              </button>
            )
          })}
        </div>

        <label className="explorer-select-wrap" title={`Projection: ${activeProjectionDef.epsgOrName}`}>
          <span className="explorer-sr-only">Basemap selector</span>
          <select
            className="explorer-select"
            value={basemap}
            onChange={(e) => setBasemap(e.target.value as BasemapId)}
            aria-label="Select basemap"
          >
            {BASEMAP_LIST.map((bm) => {
              const compatible = isBasemapCompatible(bm.id, projection)
              return (
                <option key={bm.id} value={bm.id} disabled={!compatible}>
                  {bm.name}
                  {!compatible ? ' (Globe / Mercator only)' : ''}
                </option>
              )
            })}
          </select>
        </label>

        <label className="explorer-date-chip" title="Target observation date (UTC)">
          <Calendar size={13} aria-hidden="true" />
          <input
            type="date"
            className="explorer-date-chip__input"
            value={displayDate}
            min="2000-02-24"
            max="2026-11-02"
            onChange={(e) => {
              if (!e.target.value) return
              setSelectedDate(e.target.value)
              if (gibsLayerId) setGibsDate(e.target.value)
            }}
            aria-label="Observation date"
          />
        </label>
      </div>

      <div className="explorer-toolbar__group explorer-toolbar__group--right">
        <div className="explorer-tool-strip" role="group" aria-label="Map interaction mode">
          {TOOL_BUTTONS.map((tool) => {
            const Icon = tool.icon
            const active = interactionMode === tool.id
            return (
              <button
                key={tool.id}
                type="button"
                className={`explorer-icon-btn ${active ? 'is-active' : ''}`}
                aria-pressed={active}
                onClick={() => setInteractionMode(tool.id)}
                title={tool.title}
                aria-label={tool.title}
              >
                <Icon size={15} />
                <span className="explorer-btn-label-wide">{tool.label}</span>
              </button>
            )
          })}
        </div>

        <button
          type="button"
          className={`explorer-icon-btn ${comparisonMode ? 'is-active-accent' : ''}`}
          aria-pressed={comparisonMode}
          onClick={() => setComparisonMode(!comparisonMode)}
          title="Toggle side-by-side comparison mode"
        >
          <Columns2 size={15} />
          <span className="explorer-btn-label-desktop">Compare</span>
        </button>

        <button
          type="button"
          className="explorer-icon-btn"
          onClick={onResetView}
          title="Reset camera to global extent"
          aria-label="Reset camera view"
        >
          <RotateCcw size={15} />
        </button>

        <button
          type="button"
          className={`explorer-icon-btn ${rightInspectorOpen ? 'is-active' : ''}`}
          aria-pressed={rightInspectorOpen}
          onClick={() => setRightInspectorOpen(!rightInspectorOpen)}
          title="Toggle right coordinate & AOI inspector"
          aria-label="Toggle inspector sidebar"
        >
          <PanelRight size={15} />
        </button>

        <button
          type="button"
          className={`explorer-icon-btn ${isFullscreen ? 'is-active' : ''}`}
          aria-pressed={isFullscreen}
          onClick={() => setIsFullscreen(!isFullscreen)}
          title={isFullscreen ? 'Exit full-screen map mode (Esc)' : 'Enter full-screen map mode'}
          aria-label={isFullscreen ? 'Exit full-screen mode' : 'Enter full-screen mode'}
        >
          {isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
      </div>
    </header>
  )
}
