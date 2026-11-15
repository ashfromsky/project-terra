import { EarthObservatorySection } from '../../widgets/earth-observatory/EarthObservatorySection'
import { AnalyticsWorkspaceSection } from '../../widgets/analytics-workspace/AnalyticsWorkspaceSection'
import { MvpWorkflowSection } from './MvpWorkflowSection'

export default function HomePage() {
  return (
    <div
      className="terra-home-page"
      data-node-id="5:110"
      data-name="PROJECT TERRA · Earth intelligence"
    >
      <EarthObservatorySection />
      <MvpWorkflowSection />
      <AnalyticsWorkspaceSection />
    </div>
  )
}
