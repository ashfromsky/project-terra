import { WorkspacePagePlaceholder } from '../../shared/ui/workspace-page-placeholder'
import { APP_ROUTES } from '../../shared/config/routes'

export default function ReportsPage() {
  return (
    <WorkspacePagePlaceholder
      eyebrow="REPORTS / REPRODUCIBLE SCIENTIFIC ARTIFACTS"
      title="Scientific Reports & Uncertainty Summaries"
      breadcrumb="Reports  /  Provenance snapshots  /  TERRA-SYN-2026-01"
      summary="Export reproducible comparison briefs containing AOI coordinates, observation windows, quality screening criteria, Mann–Kendall / Sen’s slope tables, and explicit methodological assumptions."
      specifications={[
        { label: 'Snapshot Identifier', value: 'TERRA-SYN-2026-01 (Synthetic demonstration)' },
        { label: 'Included Diagnostics', value: 'OLS, Seasonal Mann–Kendall, Sen’s slope, 95% CI' },
        { label: 'Provenance Tracking', value: 'Product version, DOI, native grid & QC filter' },
        { label: 'Attribution Policy', value: 'Correlation ≠ causation · Explicit uncertainty' },
      ]}
      metrics={[
        {
          eyebrow: 'SNAPSHOT ARCHIVE',
          value: 'TERRA-SYN-2026-01',
          caption: 'Baseline 2010–2019 · Observed window 2020–2025',
          tone: 'teal',
        },
        {
          eyebrow: 'SIGNIFICANCE THRESHOLD',
          value: 'α = 0.05',
          caption: 'Autocorrelation-adjusted trend inference',
          tone: 'default',
        },
        {
          eyebrow: 'EXPORT FORMATS',
          value: 'JSON / Markdown',
          caption: 'Structured metadata & provenance manifest',
          tone: 'blue',
        },
      ]}
      primaryActionLabel="Configure New Comparison"
      primaryActionTo={APP_ROUTES.comparativeAnalysis}
      secondaryActionLabel="Verify Data Sources"
      secondaryActionTo={APP_ROUTES.dataSources}
      statusNote="Report generation connects to completed backend analysis jobs once the worker runtime is active."
    />
  )
}
