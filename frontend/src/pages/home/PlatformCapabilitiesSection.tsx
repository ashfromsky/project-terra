import { Link } from 'react-router'
import { LIVE_GIBS_LAYERS } from '../../shared/config/live-environment'
import { APP_ROUTES } from '../../shared/config/routes'
import { ChevronRight } from '../../shared/ui/explorer-icons'

interface Capability {
  id: string
  title: string
  tagline: string
  description: string
  features: readonly string[]
  route: string
  isPrimary?: boolean
}

const CAPABILITIES: readonly Capability[] = [
  {
    id: 'explore',
    title: 'Live Map Explorer',
    tagline: 'Global satellite layers, AOIs, and a point readout',
    description:
      'Read NASA GIBS imagery over a full-screen map. Draw a rectangle or polygon, inspect coordinates, and carry the same view into the explorer.',
    features: [
      `${LIVE_GIBS_LAYERS.length} NASA GIBS satellite layers`,
      'OpenFreeMap vector cartography',
      'Polygon and bounding-box AOI tools',
      'Point readout and coordinate inspection',
    ],
    route: APP_ROUTES.explore,
    isPrimary: true,
  },
  {
    id: 'comparative-analysis',
    title: 'Environmental Analysis',
    tagline: 'Compare two regions or two periods',
    description:
      'Put two assessment runs side by side. Synchronized cameras and a split view keep the comparison aligned.',
    features: [
      'Synchronized side-by-side or split views',
      'Cross-temporal baseline comparison',
      'Bi-regional ecosystem contrast',
      'Layer opacity and threshold controls',
    ],
    route: APP_ROUTES.comparativeAnalysis,
  },
  {
    id: 'assessments',
    title: 'Assessments',
    tagline: 'Trend, anomaly, and resilience results over an AOI',
    description:
      'Run the statistical workflow on a selected region. Every result keeps its method, sample coverage, and limitations attached.',
    features: [
      'Seasonal Mann–Kendall trend test',
      'Theil–Sen robust rate of change',
      'Standardized z-score anomalies',
      'Four resilience dimensions',
    ],
    route: APP_ROUTES.assessments,
  },
  {
    id: 'data-sources',
    title: 'Data Sources & Providers',
    tagline: 'Provider status, product specs, and lineage',
    description:
      'Check which feeds are reachable, what resolution and cadence they carry, and where each granule came from.',
    features: [
      'Provider readiness and auth checks',
      'Spatial resolution and temporal cadence',
      'Granule discovery and ingestion',
      'Dataset provenance and lineage',
    ],
    route: APP_ROUTES.dataSources,
  },
  {
    id: 'methodology',
    title: 'Scientific Methodology',
    tagline: 'The formulas, baselines, and the limits',
    description:
      'Read the definitions, QA rules, and assumptions behind each number. Correlation is reported as correlation, not cause.',
    features: [
      'Documented baseline and anomaly models',
      'Cloud screening and QA bitmasks',
      'Sample coverage and uncertainty',
      'Explicit causal boundaries',
    ],
    route: APP_ROUTES.overview,
  },
]

export function PlatformCapabilitiesSection() {
  return (
    <section
      id="platform-capabilities"
      className="capabilities-section"
      aria-labelledby="capabilities-title"
    >
      <div className="capabilities-section__inner">
        <header className="capabilities-section__intro">
          <p className="capabilities-section__kicker">
            <span className="section-mark" aria-hidden="true" />
            Workspaces
          </p>
          <h2 id="capabilities-title" className="capabilities-section__title">
            Five ways into the same observation record
          </h2>
          <p className="capabilities-section__lede">
            Move from a place on the map to a documented answer. Each workspace keeps
            the product, date, and method visible.
          </p>
          <Link to={APP_ROUTES.explore} className="capabilities-section__link">
            Open the live map
            <ChevronRight size={15} aria-hidden="true" />
          </Link>
        </header>

        <div className="capability-list">
          {CAPABILITIES.map((item, index) => (
            <article
              key={item.id}
              className={`capability-row${
                item.isPrimary ? ' capability-row--lead' : ''
              }`}
            >
              <span className="capability-row__index" aria-hidden="true">
                {String(index + 1).padStart(2, '0')}
              </span>

              <div className="capability-row__body">
                <div className="capability-row__heading">
                  <h3 className="capability-row__title">
                    <Link to={item.route}>{item.title}</Link>
                  </h3>
                  {item.isPrimary && (
                    <span className="capability-row__lead-label">Start here</span>
                  )}
                </div>
                <p className="capability-row__tagline">{item.tagline}</p>
                <p className="capability-row__description">{item.description}</p>

                {item.isPrimary ? (
                  <ul className="capability-row__features">
                    {item.features.map((feature) => (
                      <li key={feature}>{feature}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="capability-row__meta">
                    {item.features.join(' · ')}
                  </p>
                )}
              </div>

              <Link
                to={item.route}
                className="capability-row__action"
                aria-label={`Open ${item.title}`}
              >
                <ChevronRight size={17} aria-hidden="true" />
              </Link>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
