import { WorkspacePagePlaceholder } from '../../shared/ui/workspace-page-placeholder'
import { APP_ROUTES } from '../../shared/config/routes'

export default function AssessmentsPage() {
  return (
    <WorkspacePagePlaceholder
      eyebrow="ASSESSMENTS / TERRA RESILIENCE INDEX (EXPERIMENTAL)"
      title="Ecosystem Resilience Assessments"
      breadcrumb="Assessments  /  Explainable components  /  Experimental TRI"
      summary="Inspect normalized 0–100 component scores across Resistance (30%), Recovery (35%), Stability (20%), and Inverse Sensitivity (15%). The TRI is an explicit weighted comparison signal, not a validated operational risk classification."
      specifications={[
        { label: 'Resistance (30%)', value: 'Event minimum / expected baseline NDVI' },
        { label: 'Recovery (35%)', value: 'Months required to return to 90% baseline' },
        { label: 'Stability (20%)', value: 'Post-event coefficient of variation (CV)' },
        { label: 'Inverse Sensitivity (15%)', value: '|β| NDVI response to precipitation z-score' },
      ]}
      metrics={[
        {
          eyebrow: 'A · CAATINGA (EXPERIMENTAL TRI)',
          value: '65.1',
          unit: '/ 100',
          caption: 'Resistance 62 · Recovery 68 · Stability 72 · Inv. Sens. 55',
          tone: 'teal',
        },
        {
          eyebrow: 'B · CERRADO (EXPERIMENTAL TRI)',
          value: '80.9',
          unit: '/ 100',
          caption: 'Resistance 80 · Recovery 84 · Stability 82 · Inv. Sens. 74',
          tone: 'blue',
        },
        {
          eyebrow: 'ELIGIBILITY THRESHOLD',
          value: '≥ 80%',
          caption: 'Valid months & ≥ 12 post-event observations required',
          tone: 'default',
        },
      ]}
      primaryActionLabel="Open Comparative Analysis"
      primaryActionTo={APP_ROUTES.comparativeAnalysis}
      secondaryActionLabel="Inspect Data Sources & Provenance"
      secondaryActionTo={APP_ROUTES.dataSources}
      statusNote="Weights total 100% · Higher is more resilient · Results depend on baseline, event window, and weights."
    />
  )
}
