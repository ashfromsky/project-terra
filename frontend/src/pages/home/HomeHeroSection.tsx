import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { LIVE_GIBS_LAYERS } from '../../shared/config/live-environment'
import { APP_ROUTES } from '../../shared/config/routes'
import { ChevronRight, Github } from '../../shared/ui/explorer-icons'

interface HomeHeroSectionProps {
  visual?: ReactNode
}

export function HomeHeroSection({ visual }: HomeHeroSectionProps) {
  return (
    <section className="terra-hero" aria-labelledby="terra-hero-title">
      <div className="terra-hero__inner">
        <div className="terra-hero__intro">
          <p className="terra-hero__eyebrow">
            <span className="section-mark" aria-hidden="true" />
            Earth system intelligence
          </p>

          <h1 id="terra-hero-title" className="terra-hero__title">
            Ecosystem response,
            <br />
            measured from orbit
          </h1>

          <p className="terra-hero__lede">
            PROJECT TERRA reads NASA satellite records into vegetation, temperature,
            water, and soil-moisture evidence. Inspect the map, compare places and
            periods, then follow the method behind every number.
          </p>

          <div className="terra-hero__actions">
            <Link to={APP_ROUTES.explore} className="terra-hero__cta">
              Open the live map
              <ChevronRight size={16} aria-hidden="true" />
            </Link>
            <a href="#platform-capabilities" className="terra-hero__secondary">
              How the platform works
            </a>
          </div>

          <p className="terra-hero__meta">
            Open source
            <span aria-hidden="true">·</span>
            <a
              href="https://github.com/ashfromsky/project-terra"
              target="_blank"
              rel="noopener noreferrer"
              className="terra-hero__meta-link"
            >
              <Github size={14} aria-hidden="true" />
              Source on GitHub
            </a>
            <span aria-hidden="true">·</span>
            NASA Space Apps Challenge 2026
          </p>
        </div>

        {visual ? <div className="terra-hero__visual">{visual}</div> : null}
      </div>

      <div className="terra-hero__data">
        <div className="contour-rule" aria-hidden="true" />
        <div className="terra-hero__data-inner">
          <div className="terra-hero__data-item">
            <span className="terra-hero__data-label">Live layers</span>
            <span className="terra-hero__data-value">
              {LIVE_GIBS_LAYERS.length} NASA GIBS layers
            </span>
          </div>
          <div className="terra-hero__data-item">
            <span className="terra-hero__data-label">Products</span>
            <span className="terra-hero__data-value">
              MODIS Terra · GPM IMERG · SMAP L4
            </span>
          </div>
          <div className="terra-hero__data-item">
            <span className="terra-hero__data-label">Methods</span>
            <span className="terra-hero__data-value">
              Mann–Kendall · Sen's slope · OLS
            </span>
          </div>
          <p className="terra-hero__data-note">
            Rendered GIBS imagery is contextual. Numerical results come from
            assessments and browser-side COG reads.
          </p>
        </div>
      </div>
    </section>
  )
}
