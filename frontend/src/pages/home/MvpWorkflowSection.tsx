import { Link } from 'react-router'
import { LIVE_GIBS_LAYERS } from '../../shared/config/live-environment'
import { APP_ROUTES } from '../../shared/config/routes'

const STEPS = [
  {
    title: 'Select a region',
    body: 'Explore the global map, search a place, inspect a point, or draw a rectangle/polygon AOI.',
  },
  {
    title: 'Choose environmental indicators',
    body: 'Switch NDVI, EVI, land surface temperature, precipitation, soil moisture, or snow cover.',
  },
  {
    title: 'Choose a period',
    body: 'Pick an observation date or a historical interval supported by the source product.',
  },
  {
    title: 'Explore and calculate',
    body: 'Read MODIS NDVI COG windows and NASA POWER point series directly in your browser.',
  },
  {
    title: 'Analyze results',
    body: 'Review descriptive statistics, standardized anomalies, Mann–Kendall, Theil–Sen, and limitations.',
  },
] as const

export function MvpWorkflowSection() {
  return (
    <section className="home-mvp" aria-labelledby="home-mvp-title">
      <div className="home-mvp__head">
        <div>
          <p className="home-mvp__overline">FROM A PLACE TO AN ANSWER</p>
          <h2 id="home-mvp-title">A working environmental workflow, not a demo dashboard</h2>
          <p className="home-mvp__lede">
            Open the global map, select a real environmental layer, draw an AOI, and run supported
            scientific calculations in the browser. No raster ingestion on the server.
          </p>
        </div>
        <div className="home-mvp__actions">
          <Link to={APP_ROUTES.explore} className="home-mvp__primary">
            Start exploring
          </Link>
          <Link to={APP_ROUTES.assessments} className="home-mvp__secondary">
            Existing assessments
          </Link>
        </div>
      </div>

      <ol className="home-mvp__steps">
        {STEPS.map((step, index) => (
          <li key={step.title}>
            <span className="home-mvp__step-number">{String(index + 1).padStart(2, '0')}</span>
            <strong>{step.title}</strong>
            <p>{step.body}</p>
          </li>
        ))}
      </ol>

      <p className="home-mvp__layers">
        <strong>{LIVE_GIBS_LAYERS.length} live NASA GIBS layers</strong> are connected directly from
        the browser: {LIVE_GIBS_LAYERS.map((layer) => layer.shortName).join(' · ')}.
      </p>
    </section>
  )
}
