import { HackathonAttributionSection } from './HackathonAttributionSection'
import { HomeFooter } from './HomeFooter'
import { HomeHeroSection } from './HomeHeroSection'
import { LiveEnvironmentalPreview } from './LiveEnvironmentalPreview'
import { PlatformCapabilitiesSection } from './PlatformCapabilitiesSection'

export default function HomePage() {
  return (
    <div
      className="terra-home-page"
      data-node-id="5:110"
      data-name="PROJECT TERRA · Earth intelligence"
    >
      <HomeHeroSection visual={<LiveEnvironmentalPreview />} />
      <PlatformCapabilitiesSection />
      <HackathonAttributionSection />
      <HomeFooter />
    </div>
  )
}
