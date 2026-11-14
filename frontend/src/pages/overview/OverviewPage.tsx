import { WorkspacePagePlaceholder } from '../../shared/ui/workspace-page-placeholder'
import { APP_ROUTES } from '../../shared/config/routes'
import { useHealthQuery } from '../../shared/api/health'

export default function OverviewPage() {
  const healthQuery = useHealthQuery()

  const apiStatusText = healthQuery.isPending
    ? 'Core API probe: connecting…'
    : healthQuery.isError
      ? 'Core API probe: offline (Core API unreachable)'
      : `Core API probe: online (${healthQuery.data.status})`

  return (
    <WorkspacePagePlaceholder
      eyebrow="OVERVIEW / PLATFORM SUMMARY"
      title="Global Earth System Overview"
      breadcrumb="Overview  /  Multi-indicator monitoring  /  Global land"
      summary="Synthesize planetary indicators across vegetation response, land surface thermal anomalies, precipitation regimes, and soil moisture dynamics before launching regional comparisons."
      specifications={[
        { label: 'Temporal Baseline', value: '2001–2010 / 2010–2019 reference windows' },
        { label: 'Spatial Coverage', value: 'Global land · WGS 84 / EPSG:4326' },
        { label: 'Core Indicators', value: 'MODIS LST, NDVI, EVI · GPM IMERG · SMAP' },
        { label: 'System Status', value: apiStatusText },
      ]}
      metrics={[
        {
          eyebrow: 'GLOBAL LST TREND',
          value: '+0.26',
          unit: '°C / decade',
          caption: 'OLS · Seasonally adjusted (2001–2025)',
          tone: 'coral',
        },
        {
          eyebrow: 'CONFIDENCE INTERVAL',
          value: '0.22 — 0.30',
          unit: '°C / decade',
          caption: '95% CI · p < 0.001 significant',
          tone: 'teal',
        },
        {
          eyebrow: 'QUALITY SCREENED',
          value: '96.8',
          unit: '%',
          caption: '300 monthly composites verified',
          tone: 'default',
        },
      ]}
      primaryActionLabel="Open Earth Observatory"
      primaryActionTo={APP_ROUTES.home}
      secondaryActionLabel="Configure Comparative Analysis"
      secondaryActionTo={APP_ROUTES.comparativeAnalysis}
      statusNote="Select a region in the Earth Observatory or open Comparative Analysis to inspect paired AOI trajectories."
    />
  )
}
