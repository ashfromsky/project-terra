import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { HackathonAttributionSection } from '../HackathonAttributionSection'
import { HomeFooter } from '../HomeFooter'
import { HomeHeroSection } from '../HomeHeroSection'
import { PlatformCapabilitiesSection } from '../PlatformCapabilitiesSection'

describe('HomePage sections', () => {
  it('renders HomeHeroSection with branding, CTAs, and Space Apps attribution', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <HomeHeroSection />
      </MemoryRouter>,
    )

    expect(html).toContain('Ecosystem response,')
    expect(html).toContain('measured from orbit')
    expect(html).toContain('PROJECT TERRA')
    expect(html).toContain('NASA Space Apps Challenge 2026')
    expect(html).toContain('Open the live map')
    expect(html).toContain('href="/explore"')
    expect(html).toContain('How the platform works')
    expect(html).toContain('href="#platform-capabilities"')
    expect(html).toContain('https://github.com/ashfromsky/project-terra')
    expect(html).toContain('Rendered GIBS imagery is contextual')
  })

  it('renders PlatformCapabilitiesSection with all 5 functional platform routes', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PlatformCapabilitiesSection />
      </MemoryRouter>,
    )

    expect(html).toContain('Live Map Explorer')
    expect(html).toContain('href="/explore"')

    expect(html).toContain('Environmental Analysis')
    expect(html).toContain('href="/comparative-analysis"')

    expect(html).toContain('Assessments')
    expect(html).toContain('href="/assessments"')

    expect(html).toContain('Data Sources &amp; Providers')
    expect(html).toContain('href="/data-sources"')

    expect(html).toContain('Scientific Methodology')
    expect(html).toContain('href="/overview"')
  })

  it('renders HackathonAttributionSection with accurate disclaimer and GitHub repository link', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <HackathonAttributionSection />
      </MemoryRouter>,
    )

    expect(html).toContain('Built during NASA Space Apps Challenge 2026')
    expect(html).toContain('Non-Affiliation Notice')
    expect(html).toContain('not an official NASA product')
    expect(html).toContain('https://github.com/ashfromsky/project-terra')
    expect(html).toContain('ashfromsky / project-terra')
  })

  it('renders HomeFooter with complete links, indicators, and provenance notice', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <HomeFooter />
      </MemoryRouter>,
    )

    expect(html).toContain('PROJECT')
    expect(html).toContain('TERRA')
    expect(html).toContain('NASA Space Apps Challenge 2026')
    expect(html).toContain('href="/explore"')
    expect(html).toContain('href="/assessments"')
    expect(html).toContain('href="/data-sources"')
    expect(html).toContain('https://github.com/ashfromsky/project-terra')
    expect(html).toContain('Correlation does not establish causation')
  })
})
