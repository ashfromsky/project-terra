import { useSearchParams } from 'react-router'
import { WorkspacePagePlaceholder } from '../../shared/ui/workspace-page-placeholder'
import { APP_ROUTES } from '../../shared/config/routes'
import { useUiStore } from '../../shared/store/ui-store'

export default function ExplorePage() {
  const [searchParams] = useSearchParams()
  const query = searchParams.get('q')
  const selectedVariable = useUiStore((state) => state.selectedVariable)
  const selectedRegion = useUiStore((state) => state.selectedRegion)

  return (
    <WorkspacePagePlaceholder
      eyebrow="EXPLORE / GEOSPATIAL OBSERVATORY"
      title={query ? `Geospatial Exploration: “${query}”` : 'Interactive Geospatial Exploration'}
      breadcrumb={`Explore  /  ${selectedVariable}  /  ${selectedRegion}`}
      summary="Inspect multi-resolution raster layers, draw custom areas of interest (AOIs), and examine pixel-level quality flags and seasonal anomaly trajectories."
      specifications={[
        { label: 'Active Variable', value: selectedVariable },
        { label: 'Geographic Scope', value: selectedRegion },
        { label: 'Projection', value: 'WGS 84 / EPSG:4326 · Native resolution preserved' },
        { label: 'Observation Window', value: 'Jan 2001 — Dec 2025 · Monthly composites' },
      ]}
      metrics={[
        {
          eyebrow: 'ACTIVE REGION',
          value: selectedRegion,
          caption: 'Synchronized with Earth Observatory selection',
          tone: 'teal',
        },
        {
          eyebrow: 'AMAZON BASIN HOTSPOT',
          value: '+0.31',
          unit: '°C / decade',
          caption: 'p < 0.001 · Significant warming trend',
          tone: 'coral',
        },
        {
          eyebrow: 'SPATIAL GRID',
          value: '0.05° / 250 m',
          caption: 'MOD11C3 & MOD13Q1 native grids',
          tone: 'blue',
        },
      ]}
      primaryActionLabel="Launch Comparative Analysis"
      primaryActionTo={APP_ROUTES.comparativeAnalysis}
      secondaryActionLabel="Return to Earth Observatory"
      secondaryActionTo={APP_ROUTES.home}
      statusNote="Dedicated full-screen layer controls and pixel inspection tools connect here as backend ingestion endpoints come online."
    />
  )
}
